from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator


class AzureClientConfig(BaseModel):
    """
    Configuration class for creating an Azure Blob Storage BlobServiceClient

    One of connection_string or account_url is required. Credentials are resolved in this order:
        1. connection_string: carries the account endpoint and credentials (also used for Azurite)
        2. account_url + sas_token
        3. account_url + account_key
        4. account_url + DefaultAzureCredential (managed identity, workload identity,
           AZURE_CLIENT_ID/AZURE_TENANT_ID/AZURE_CLIENT_SECRET service principal, Azure CLI, ...)

    Attributes:
        account_url (Optional[str]): Blob service endpoint, e.g. https://<account>.blob.core.windows.net
        connection_string (Optional[str]): Azure Storage connection string
        account_key (Optional[str]): Storage account shared key
        sas_token (Optional[str]): Shared access signature token
        max_retries (int) (default: 3): Maximum number of retry attempts for failed requests
        max_block_size (int): Block size used for chunked uploads
        max_single_put_size (int): Blobs up to this size are uploaded with a single PUT request
        max_chunk_get_size (int): Chunk size used for chunked downloads
        max_single_get_size (int): Size of the first ranged GET request of a download

    Note:
        The model is frozen so it is hashable, which is required for @functools.cache
        to use it as a dictionary key.
        For more details on DefaultAzureCredential see:
        https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential
    """

    model_config = ConfigDict(frozen=True)

    account_url: Optional[str] = None
    connection_string: Optional[str] = None
    account_key: Optional[str] = None
    sas_token: Optional[str] = None
    max_retries: int = 3

    max_block_size: int = 50 * 1024 * 1024  # 50MB
    max_single_put_size: int = 64 * 1024 * 1024  # 64MB
    max_chunk_get_size: int = 50 * 1024 * 1024  # 50MB
    max_single_get_size: int = 32 * 1024 * 1024  # 32MB

    @model_validator(mode="after")
    def _require_endpoint(self) -> "AzureClientConfig":
        if not self.connection_string and not self.account_url:
            raise ValueError("Either connection_string or account_url must be set")
        return self
