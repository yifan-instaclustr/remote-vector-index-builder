# Copyright OpenSearch Contributors
# SPDX-License-Identifier: Apache-2.0
#
# The OpenSearch Contributors require contributions made to
# this file be licensed under the Apache-2.0 license or a
# compatible open source license.
import pytest
from unittest.mock import Mock, patch
from app.models.workflow import BuildWorkflow
from app.services.index_builder import IndexBuilder


@pytest.fixture
def index_builder():
    return IndexBuilder()


@pytest.fixture
def mock_workflow():
    workflow = Mock(spec=BuildWorkflow)
    workflow.index_build_parameters = {"param1": "value1", "param2": "value2"}
    return workflow


def test_build_index_success(index_builder, mock_workflow):
    """Test successful index building"""
    with patch("app.services.index_builder.run_tasks") as mock_run_tasks:
        mock_result = Mock()
        mock_result.file_name = "/path/to/index"
        mock_result.error = None
        mock_run_tasks.return_value = mock_result

        success, path, error = index_builder.build_index(mock_workflow)

        assert success is True
        assert path == "/path/to/index"
        assert error is None
        mock_run_tasks.assert_called_once()


def test_build_index_failure(index_builder, mock_workflow):
    """Test failed index building"""
    with patch("app.services.index_builder.run_tasks") as mock_run_tasks:
        mock_result = Mock()
        mock_result.file_name = None
        mock_result.error = "Build failed"
        mock_run_tasks.return_value = mock_result

        success, path, error = index_builder.build_index(mock_workflow)

        assert success is False
        assert path is None
        assert error == "Build failed"
        mock_run_tasks.assert_called_once()


def test_build_index_passes_disable_extra_args_from_env(
    index_builder, mock_workflow, monkeypatch
):
    monkeypatch.setenv("S3_DISABLE_EXTRA_ARGS", "true")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with patch("app.services.index_builder.run_tasks") as mock_run_tasks:
        mock_result = Mock()
        mock_result.file_name = "/path/to/index"
        mock_result.error = None
        mock_run_tasks.return_value = mock_result

        index_builder.build_index(mock_workflow)

        object_store_config = mock_run_tasks.call_args.args[1]
        assert object_store_config["disable_extra_args"] is True


def test_build_index_without_azure_env(index_builder, mock_workflow, monkeypatch):
    """Azure client config is omitted when no Azure endpoint is configured"""
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_URL", raising=False)
    with patch("app.services.index_builder.run_tasks") as mock_run_tasks:
        mock_run_tasks.return_value = Mock(file_name="/path/to/index", error=None)

        index_builder.build_index(mock_workflow)

        object_store_config = mock_run_tasks.call_args.args[1]
        assert "s3_client_config" in object_store_config
        assert "azure_client_config" not in object_store_config


def test_build_index_with_azure_env(index_builder, mock_workflow, monkeypatch):
    """Azure client config is built from environment variables"""
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.setenv(
        "AZURE_STORAGE_ACCOUNT_URL", "https://testaccount.blob.core.windows.net"
    )
    monkeypatch.setenv("AZURE_STORAGE_SAS_TOKEN", "sv=1&sig=abc")
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_KEY", raising=False)
    with patch("app.services.index_builder.run_tasks") as mock_run_tasks:
        mock_run_tasks.return_value = Mock(file_name="/path/to/index", error=None)

        index_builder.build_index(mock_workflow)

        azure_client_config = mock_run_tasks.call_args.args[1]["azure_client_config"]
        assert (
            azure_client_config.account_url
            == "https://testaccount.blob.core.windows.net"
        )
        assert azure_client_config.sas_token == "sv=1&sig=abc"
        assert azure_client_config.connection_string is None
