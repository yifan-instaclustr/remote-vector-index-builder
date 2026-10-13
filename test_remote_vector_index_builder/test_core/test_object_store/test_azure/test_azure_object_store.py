# Copyright OpenSearch Contributors
# SPDX-License-Identifier: Apache-2.0
#
# The OpenSearch Contributors require contributions made to
# this file be licensed under the Apache-2.0 license or a
# compatible open source license.

from io import BytesIO
from unittest.mock import ANY, Mock, patch

import pytest
from azure.core.credentials import AzureSasCredential
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from core.common.exceptions import BlobError
from core.object_store.azure.azure_object_store import (
    AzureBlobObjectStore,
    get_blob_service_client,
)
from core.object_store.azure.azure_object_store_config import AzureClientConfig
from pydantic import ValidationError

TEST_ACCOUNT_URL = "https://testaccount.blob.core.windows.net"


@pytest.fixture(autouse=True)
def mock_logger():
    with patch("core.object_store.azure.azure_object_store.logger"):
        yield


@pytest.fixture(autouse=True)
def clear_client_cache():
    get_blob_service_client.cache_clear()
    yield
    get_blob_service_client.cache_clear()


@pytest.fixture
def azure_object_store_config():
    return {
        "debug": False,
        "download_transfer_config": {"max_concurrency": 4},
        "upload_transfer_config": {"max_concurrency": 8},
        "azure_client_config": AzureClientConfig(
            account_url=TEST_ACCOUNT_URL, max_retries=4
        ),
    }


@pytest.fixture
def azure_store(index_build_parameters, azure_object_store_config):
    with patch("core.object_store.azure.azure_object_store.get_blob_service_client"):
        yield AzureBlobObjectStore(index_build_parameters, azure_object_store_config)


@pytest.fixture
def blob_client(azure_store):
    client = Mock()
    azure_store.container_client.get_blob_client.return_value = client
    return client


def test_client_config_requires_endpoint():
    with pytest.raises(ValidationError):
        AzureClientConfig()


def test_client_config_is_hashable():
    assert hash(AzureClientConfig(account_url=TEST_ACCOUNT_URL)) == hash(
        AzureClientConfig(account_url=TEST_ACCOUNT_URL)
    )


def test_get_blob_service_client_from_connection_string():
    with patch(
        "core.object_store.azure.azure_object_store.BlobServiceClient"
    ) as mock_client_cls:
        config = AzureClientConfig(connection_string="conn-str", max_retries=5)
        client1 = get_blob_service_client(config)
        client2 = get_blob_service_client(config)

        assert client1 is client2
        mock_client_cls.from_connection_string.assert_called_once_with(
            "conn-str",
            retry_total=5,
            max_block_size=config.max_block_size,
            max_single_put_size=config.max_single_put_size,
            max_chunk_get_size=config.max_chunk_get_size,
            max_single_get_size=config.max_single_get_size,
        )
        mock_client_cls.assert_not_called()


def test_get_blob_service_client_with_sas_token():
    with patch(
        "core.object_store.azure.azure_object_store.BlobServiceClient"
    ) as mock_client_cls:
        get_blob_service_client(
            AzureClientConfig(account_url=TEST_ACCOUNT_URL, sas_token="?sv=1&sig=abc")
        )

        credential = mock_client_cls.call_args.kwargs["credential"]
        assert isinstance(credential, AzureSasCredential)
        assert credential.signature == "sv=1&sig=abc"
        assert mock_client_cls.call_args.kwargs["account_url"] == TEST_ACCOUNT_URL


def test_get_blob_service_client_with_account_key():
    with patch(
        "core.object_store.azure.azure_object_store.BlobServiceClient"
    ) as mock_client_cls:
        get_blob_service_client(
            AzureClientConfig(account_url=TEST_ACCOUNT_URL, account_key="key")
        )

        mock_client_cls.assert_called_once_with(
            account_url=TEST_ACCOUNT_URL,
            credential="key",
            retry_total=3,
            max_block_size=ANY,
            max_single_put_size=ANY,
            max_chunk_get_size=ANY,
            max_single_get_size=ANY,
        )


def test_get_blob_service_client_defaults_to_default_azure_credential():
    with (
        patch(
            "core.object_store.azure.azure_object_store.BlobServiceClient"
        ) as mock_client_cls,
        patch(
            "core.object_store.azure.azure_object_store.DefaultAzureCredential"
        ) as mock_credential_cls,
    ):
        get_blob_service_client(AzureClientConfig(account_url=TEST_ACCOUNT_URL))

        mock_credential_cls.assert_called_once_with()
        assert (
            mock_client_cls.call_args.kwargs["credential"]
            is mock_credential_cls.return_value
        )


def test_get_blob_service_client_caches_per_config():
    with patch(
        "core.object_store.azure.azure_object_store.BlobServiceClient",
        side_effect=lambda **kwargs: Mock(),
    ) as mock_client_cls:
        client1 = get_blob_service_client(
            AzureClientConfig(account_url=TEST_ACCOUNT_URL, account_key="key1")
        )
        client2 = get_blob_service_client(
            AzureClientConfig(account_url=TEST_ACCOUNT_URL, account_key="key2")
        )
        assert client1 is not client2
        assert mock_client_cls.call_count == 2


def test_initialization(index_build_parameters, azure_object_store_config):
    with patch(
        "core.object_store.azure.azure_object_store.get_blob_service_client"
    ) as mock_get_client:
        store = AzureBlobObjectStore(index_build_parameters, azure_object_store_config)

        assert store.container == index_build_parameters.container_name
        assert store.max_retries == 4
        mock_get_client.return_value.get_container_client.assert_called_once_with(
            index_build_parameters.container_name
        )
        assert store.download_transfer_config["max_concurrency"] == 4
        assert store.upload_transfer_config["max_concurrency"] == 8
        assert store.download_args == {}
        assert store.upload_args == {"overwrite": True}
        assert not store.debug


def test_initialization_without_client_config_fails(index_build_parameters):
    with pytest.raises(ValueError, match="azure_client_config"):
        AzureBlobObjectStore(index_build_parameters, {})


def test_custom_args_override_defaults(index_build_parameters):
    config = {
        "azure_client_config": AzureClientConfig(account_url=TEST_ACCOUNT_URL),
        "download_args": {"validate_content": True},
        "upload_args": {"overwrite": False, "validate_content": True},
    }
    with patch("core.object_store.azure.azure_object_store.get_blob_service_client"):
        store = AzureBlobObjectStore(index_build_parameters, config)

        assert store.download_args == {"validate_content": True}
        assert store.upload_args == {"overwrite": False, "validate_content": True}
        assert (
            store.upload_transfer_config["max_concurrency"]
            == store.DEFAULT_UPLOAD_TRANSFER_CONFIG["max_concurrency"]
        )


def test_read_blob_success(azure_store, blob_client):
    buffer = BytesIO()
    azure_store.read_blob("test/path", buffer)

    azure_store.container_client.get_blob_client.assert_called_once_with("test/path")
    blob_client.download_blob.assert_called_once_with(
        progress_hook=None, max_concurrency=4
    )
    blob_client.download_blob.return_value.readinto.assert_called_once_with(buffer)


def test_read_blob_with_debug(index_build_parameters, azure_object_store_config):
    azure_object_store_config["debug"] = True
    with patch("core.object_store.azure.azure_object_store.get_blob_service_client"):
        store = AzureBlobObjectStore(index_build_parameters, azure_object_store_config)
    blob_client = store.container_client.get_blob_client.return_value

    store.read_blob("test/path", BytesIO())

    hook = blob_client.download_blob.call_args.kwargs["progress_hook"]
    assert hook is not None
    assert store._read_progress == 0
    hook(100, 150)
    assert store._read_progress == 100
    hook(150, 150)
    assert store._read_progress == 150


def test_read_blob_azure_error(azure_store, blob_client):
    blob_client.download_blob.side_effect = ResourceNotFoundError("not found")
    with pytest.raises(BlobError):
        azure_store.read_blob("test/path", BytesIO())


def test_read_blob_type_error(azure_store, blob_client):
    blob_client.download_blob.side_effect = TypeError("unexpected keyword argument")
    with pytest.raises(BlobError):
        azure_store.read_blob("test/path", BytesIO())


def test_write_blob_from_disk_success(azure_store, blob_client, tmp_path):
    local_file = tmp_path / "index.faiss"
    local_file.write_bytes(b"index-bytes")

    azure_store.write_blob(str(local_file), "remote/path")

    azure_store.container_client.get_blob_client.assert_called_once_with("remote/path")
    blob_client.upload_blob.assert_called_once_with(
        ANY, progress_hook=None, max_concurrency=8, overwrite=True
    )
    assert blob_client.upload_blob.call_args.args[0].name == str(local_file)


def test_write_blob_from_buffer_success(azure_store, blob_client):
    buffer = BytesIO(b"index-bytes")
    buffer.seek(5)

    azure_store.write_blob(buffer, "remote/path")

    blob_client.upload_blob.assert_called_once_with(
        buffer, progress_hook=None, max_concurrency=8, overwrite=True
    )
    assert buffer.tell() == 0


def test_write_blob_with_debug(index_build_parameters, azure_object_store_config):
    azure_object_store_config["debug"] = True
    with patch("core.object_store.azure.azure_object_store.get_blob_service_client"):
        store = AzureBlobObjectStore(index_build_parameters, azure_object_store_config)
    blob_client = store.container_client.get_blob_client.return_value

    store.write_blob(BytesIO(b"data"), "remote/path")

    hook = blob_client.upload_blob.call_args.kwargs["progress_hook"]
    assert hook is not None
    assert store._write_progress == 0
    hook(100, None)
    assert store._write_progress == 100
    hook(150, None)
    assert store._write_progress == 150


def test_write_blob_azure_error(azure_store, blob_client):
    blob_client.upload_blob.side_effect = HttpResponseError("Server busy")
    with pytest.raises(BlobError):
        azure_store.write_blob(BytesIO(b"data"), "remote/path")


def test_write_blob_type_error(azure_store, blob_client):
    blob_client.upload_blob.side_effect = TypeError("unexpected keyword argument")
    with pytest.raises(BlobError):
        azure_store.write_blob(BytesIO(b"data"), "remote/path")
