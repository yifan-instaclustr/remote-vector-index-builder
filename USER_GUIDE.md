# User Guide: OpenSearch Remote Vector Index Builder

## Getting Started

### 1. Provision an Instance
System requirements:
- NVIDIA GPU powered machine with CUDA Toolkit and Docker installed.
  - ex. AWS EC2 `g5.2xlarge` instance running Deep Learning OSS Nvidia Driver AMI.

## Pull Docker Image
Once your GPU instance is created, pull the Remote Vector Index Builder Docker image:
```bash
docker pull opensearchstaging/remote-vector-index-builder:api-latest
```

## Running the Service
### Prerequisites
In order to connect to an object store to transfer vectors and completed index builds, the GPU instance should have the relevant read and write permissions. 

For Amazon S3, this means creating an IAM role for the EC2 instance to access the S3 bucket. For more information, see the [S3 user guide.](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-iam.html)

For Azure Blob Storage, the identity used by the service needs read and write access to the container, for example the `Storage Blob Data Contributor` role. See [Authorize access to blobs using Microsoft Entra ID.](https://learn.microsoft.com/en-us/azure/storage/blobs/authorize-access-azure-active-directory)

Additionally, the EC2 instance should be configured to allow inbound traffic from the OpenSearch cluster to allow the cluster to send build and status requests. See [Security Groups Documentation](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-security-groups.html).

### Starting the Docker Container
```bash
docker run --gpus all -p 80:1025 opensearchstaging/remote-vector-index-builder:api-latest
```
If another Docker process is already running on this port, you may get an error that port 80 is already in use. To fix this, you can either kill the existing process on the port or use a different port.

After successfully running the previous command, the remote build service will be available at the instance's public IP address on port 80 (or whichever port was chosen previously).

### Using Azure Blob Storage
Build requests with `"repository_type": "azure"` read and write blobs in the request's `container_name`. The OpenSearch `azure` repository stores the storage account in the node keystore rather than in the repository settings, so the build service must be configured separately for the same storage account, using the following environment variables:

| Variable | Description |
|---|---|
| `AZURE_STORAGE_ACCOUNT_URL` | Blob service endpoint, e.g. `https://<account>.blob.core.windows.net` |
| `AZURE_STORAGE_CONNECTION_STRING` | Connection string, used instead of `AZURE_STORAGE_ACCOUNT_URL` (e.g. for an account key or [Azurite](https://learn.microsoft.com/en-us/azure/storage/common/storage-use-azurite)) |
| `AZURE_STORAGE_SAS_TOKEN` | Optional shared access signature used with `AZURE_STORAGE_ACCOUNT_URL` |
| `AZURE_STORAGE_ACCOUNT_KEY` | Optional storage account key used with `AZURE_STORAGE_ACCOUNT_URL` |

If only `AZURE_STORAGE_ACCOUNT_URL` is set, the service authenticates with [DefaultAzureCredential](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential), which supports managed identity, workload identity, and the `AZURE_CLIENT_ID`/`AZURE_TENANT_ID`/`AZURE_CLIENT_SECRET` service principal variables.

```bash
docker run --gpus all -p 80:1025 -e AZURE_STORAGE_ACCOUNT_URL=https://<account>.blob.core.windows.net opensearchstaging/remote-vector-index-builder:api-latest
```

For information on configuring OpenSearch to use this service, please refer to the [OpenSearch k-NN documentation.](https://docs.opensearch.org/docs/latest/vector-search/)

## Additional Information

You are free to implement a different API server, as long as it conforms to the [Remote Vector Service API Contract](./API.md).
This custom API image can still use the `core` image libraries to execute the index build workflow.