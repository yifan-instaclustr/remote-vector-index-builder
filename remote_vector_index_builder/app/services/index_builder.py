# Copyright OpenSearch Contributors
# SPDX-License-Identifier: Apache-2.0
#
# The OpenSearch Contributors require contributions made to
# this file be licensed under the Apache-2.0 license or a
# compatible open source license.

import logging
import os
from typing import Any, Dict, Optional, Tuple
from app.models.workflow import BuildWorkflow
from core.object_store.azure.azure_object_store_config import AzureClientConfig
from core.object_store.s3.s3_object_store_config import S3ClientConfig
from core.common.models import IndexSerializationMode
from core.tasks import run_tasks

logger = logging.getLogger(__name__)


class IndexBuilder:
    """
    Handles the building of indexes based on provided workflows.
    """

    def build_index(
        self, workflow: BuildWorkflow
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Builds the index for the given workflow, using the run_tasks function

        Args:
            workflow (BuildWorkflow): Workflow containing index build parameters

        Returns:
            Tuple[bool, Optional[str], Optional[str]]: A tuple containing:
                - Success status (True/False)
                - Index path if successful, None otherwise
                - Error message if failed, None otherwise
        """
        index_serialization_mode = os.environ.get(
            "INDEX_SERIALIZATION_MODE", IndexSerializationMode.DISK
        )
        disable_extra_args = os.environ.get(
            "S3_DISABLE_EXTRA_ARGS", ""
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        object_store_config: Dict[str, Any] = {
            "disable_extra_args": disable_extra_args,
        }
        s3_client_config = self._get_s3_client_config()
        if s3_client_config is not None:
            object_store_config["s3_client_config"] = s3_client_config
        azure_client_config = self._get_azure_client_config()
        if azure_client_config is not None:
            object_store_config["azure_client_config"] = azure_client_config

        result = run_tasks(
            workflow.index_build_parameters,
            object_store_config,
            index_serialization_mode,
        )
        if not result.file_name:
            return False, None, result.error
        return True, result.file_name, None

    @staticmethod
    def _get_s3_client_config() -> Optional[S3ClientConfig]:
        """
        Builds the S3 client configuration from environment variables.

        Returns:
            Optional[S3ClientConfig]: The configuration, or None if AWS_DEFAULT_REGION is not set
        """
        region_name = os.environ.get("AWS_DEFAULT_REGION")
        if not region_name:
            return None
        return S3ClientConfig(
            region_name=region_name,
            endpoint_url=os.environ.get("S3_ENDPOINT_URL", None),
        )

    @staticmethod
    def _get_azure_client_config() -> Optional[AzureClientConfig]:
        """
        Builds the Azure Blob Storage client configuration from environment variables.

        Returns:
            Optional[AzureClientConfig]: The configuration, or None if neither
                AZURE_STORAGE_CONNECTION_STRING nor AZURE_STORAGE_ACCOUNT_URL is set
        """
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
        if not connection_string and not account_url:
            return None
        return AzureClientConfig(
            connection_string=connection_string,
            account_url=account_url,
            account_key=os.environ.get("AZURE_STORAGE_ACCOUNT_KEY"),
            sas_token=os.environ.get("AZURE_STORAGE_SAS_TOKEN"),
        )
