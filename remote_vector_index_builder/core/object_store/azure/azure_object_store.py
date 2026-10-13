# Copyright OpenSearch Contributors
# SPDX-License-Identifier: Apache-2.0
#
# The OpenSearch Contributors require contributions made to
# this file be licensed under the Apache-2.0 license or a
# compatible open source license.

import logging
import threading
from functools import cache
from io import BytesIO
from typing import Any, Dict, Optional, Union

from azure.core.credentials import AzureSasCredential
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from core.common.exceptions import BlobError
from core.common.models import IndexBuildParameters
from core.object_store.azure.azure_object_store_config import AzureClientConfig
from core.object_store.object_store import ObjectStore
from core.object_store.s3.s3_object_store import get_cpus

logger = logging.getLogger(__name__)


@cache
def get_blob_service_client(
    azure_client_config: AzureClientConfig,
) -> BlobServiceClient:
    """Create or retrieve a cached Azure BlobServiceClient.

    Args:
        azure_client_config (AzureClientConfig): Configuration class for creating the BlobServiceClient

    Returns:
        BlobServiceClient: Configured Azure Blob Storage client instance
    """
    client_kwargs = {
        "retry_total": azure_client_config.max_retries,
        "max_block_size": azure_client_config.max_block_size,
        "max_single_put_size": azure_client_config.max_single_put_size,
        "max_chunk_get_size": azure_client_config.max_chunk_get_size,
        "max_single_get_size": azure_client_config.max_single_get_size,
    }

    if azure_client_config.connection_string:
        return BlobServiceClient.from_connection_string(
            azure_client_config.connection_string, **client_kwargs
        )

    if azure_client_config.sas_token:
        credential: Any = AzureSasCredential(azure_client_config.sas_token.lstrip("?"))
    elif azure_client_config.account_key:
        credential = azure_client_config.account_key
    else:
        credential = DefaultAzureCredential()

    return BlobServiceClient(
        account_url=azure_client_config.account_url,
        credential=credential,
        **client_kwargs,
    )


class AzureBlobObjectStore(ObjectStore):
    """Azure Blob Storage implementation of the ObjectStore interface for managing vector data files.

    This class handles interactions with Azure Blob Storage, including blob uploads and downloads,
    with configurable retry logic and transfer settings for optimal performance.

    Attributes:
        DEFAULT_DOWNLOAD_TRANSFER_CONFIG (dict): Default keyword arguments for transfer tuning on
            BlobClient.download_blob, including concurrency
        DEFAULT_UPLOAD_TRANSFER_CONFIG (dict): Default keyword arguments for transfer tuning on
            BlobClient.upload_blob, including concurrency
        DEFAULT_DOWNLOAD_ARGS (dict): Default extra keyword arguments for BlobClient.download_blob
        DEFAULT_UPLOAD_ARGS (dict): Default extra keyword arguments for BlobClient.upload_blob.
            Overwrites existing blobs, matching S3 PutObject semantics

    Args:
        index_build_params (IndexBuildParameters): Parameters for the index building process
        object_store_config (Dict[str, Any]): Configuration options for Azure Blob Storage interactions
    """

    def __init__(
        self,
        index_build_params: IndexBuildParameters,
        object_store_config: Dict[str, Any],
    ):
        """Initialize the AzureBlobObjectStore with the given parameters and configuration.

        Args:
            index_build_params (IndexBuildParameters): Contains the container name and other
                index building parameters

            object_store_config (Dict[str, Any]): Configuration dictionary containing:
                - azure_client_config (AzureClientConfig) (Required): see AzureClientConfig
                - download_transfer_config (Dict[str, Any]): e.g. max_concurrency for downloads
                - upload_transfer_config (Dict[str, Any]): e.g. max_concurrency for uploads
                - download_args (Dict[str, Any]): extra kwargs for BlobClient.download_blob
                - upload_args (Dict[str, Any]): extra kwargs for BlobClient.upload_blob
                - debug: Turns on debug mode (default: False)

        Raises:
            ValueError: If azure_client_config is missing from object_store_config
        """

        self.DEFAULT_DOWNLOAD_TRANSFER_CONFIG = {
            "max_concurrency": get_cpus(factor=0.625),
        }

        self.DEFAULT_UPLOAD_TRANSFER_CONFIG = {
            "max_concurrency": get_cpus(factor=0.5),
        }

        self.DEFAULT_DOWNLOAD_ARGS: Dict[str, Any] = {}

        self.DEFAULT_UPLOAD_ARGS = {
            "overwrite": True,
        }

        azure_client_config: Optional[AzureClientConfig] = object_store_config.get(
            "azure_client_config"
        )
        if azure_client_config is None:
            raise ValueError(
                "azure_client_config is required for the azure object store. Set "
                "AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_URL on the builder."
            )

        self.container = index_build_params.container_name
        self.max_retries = azure_client_config.max_retries

        self.blob_service_client = get_blob_service_client(azure_client_config)
        self.container_client = self.blob_service_client.get_container_client(
            self.container
        )

        self.download_transfer_config = AzureBlobObjectStore._create_custom_config(
            object_store_config.get("download_transfer_config", {}),
            self.DEFAULT_DOWNLOAD_TRANSFER_CONFIG,
        )
        self.download_args = AzureBlobObjectStore._create_custom_config(
            object_store_config.get("download_args", {}), self.DEFAULT_DOWNLOAD_ARGS
        )
        self.upload_transfer_config = AzureBlobObjectStore._create_custom_config(
            object_store_config.get("upload_transfer_config", {}),
            self.DEFAULT_UPLOAD_TRANSFER_CONFIG,
        )
        self.upload_args = AzureBlobObjectStore._create_custom_config(
            object_store_config.get("upload_args", {}), self.DEFAULT_UPLOAD_ARGS
        )

        self.debug = object_store_config.get("debug", False)

        # Debug mode provides progress tracking on downloads and uploads
        if self.debug:
            self._read_progress = 0
            self._read_progress_lock = threading.Lock()
            self._write_progress = 0
            self._write_progress_lock = threading.Lock()

    @staticmethod
    def _create_custom_config(
        custom_config: Dict[str, Any], default_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merges custom configuration parameters with default values, ensuring any
        unspecified parameters retain their default settings.

        Args:
            custom_config (dict): User-provided configuration parameters to override defaults
            default_config (dict): Base configuration parameters that will be used if not
                specified in custom_config

        Returns:
            dict: A merged configuration dictionary, where custom values take precedence over defaults
        """
        config_params = default_config.copy()
        config_params.update(custom_config)
        return config_params

    def read_blob(self, remote_store_path: str, bytes_buffer: BytesIO) -> None:
        """
        Downloads a blob from Azure Blob Storage to the provided bytes buffer.

        Args:
            remote_store_path (str): The blob name (path) within the container to download
            bytes_buffer (BytesIO): A bytes buffer to store the downloaded data

        Returns:
            None

        Note:
            - The Azure SDK retries transient failures according to max_retries
            - The SDK downloads in parallel ranged chunks when the blob is larger than
              max_single_get_size

        Raises:
            BlobError: If download fails after all retry attempts or encounters non-retryable error
        """
        progress_hook = None

        # Set up progress callback, if debug mode is on
        if self.debug:
            with self._read_progress_lock:
                self._read_progress = 0

            def hook(current: int, total: Optional[int]) -> None:
                with self._read_progress_lock:
                    self._read_progress = current
                    logger.info(f"Downloaded: {self._read_progress:,} bytes")

            progress_hook = hook

        try:
            blob_client = self.container_client.get_blob_client(remote_store_path)
            downloader = blob_client.download_blob(
                progress_hook=progress_hook,
                **self.download_transfer_config,
                **self.download_args,
            )
            downloader.readinto(bytes_buffer)
        except TypeError as e:
            raise BlobError(f"Error calling BlobClient.download_blob: {e}") from e
        except AzureError as e:
            raise BlobError(f"Error downloading file: {e}") from e

    def write_blob(self, data: Union[str, BytesIO], remote_store_path: str) -> None:
        """
        Uploads a local file or buffer to Azure Blob Storage.

        Args:
            data (Union[str, BytesIO]): Either a string representing a local file path
                or a BytesIO object representing a buffer
            remote_store_path (str): The blob name (path) within the container to upload to

        Returns:
            None

        Note:
            - The Azure SDK retries transient failures according to max_retries
            - The SDK uploads in parallel blocks when the data is larger than max_single_put_size

        Raises:
            BlobError: If upload fails after all retry attempts or encounters a non-retryable error
        """
        progress_hook = None

        # Set up progress callback, if debug mode is on
        if self.debug:
            with self._write_progress_lock:
                self._write_progress = 0

            def hook(current: int, total: Optional[int]) -> None:
                with self._write_progress_lock:
                    self._write_progress = current
                    logger.info(f"Uploaded: {self._write_progress:,} bytes")

            progress_hook = hook

        try:
            blob_client = self.container_client.get_blob_client(remote_store_path)
            if isinstance(data, BytesIO):
                data.seek(0)
                self._upload(blob_client, data, progress_hook)
            else:
                with open(data, "rb") as f:
                    self._upload(blob_client, f, progress_hook)
        except TypeError as e:
            raise BlobError(f"Error calling BlobClient.upload_blob: {e}") from e
        except AzureError as e:
            raise BlobError(f"Error uploading file: {e}") from e

    def _upload(self, blob_client, stream, progress_hook) -> None:
        blob_client.upload_blob(
            stream,
            progress_hook=progress_hook,
            **self.upload_transfer_config,
            **self.upload_args,
        )
