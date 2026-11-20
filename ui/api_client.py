"""Client HTTP mỏng gọi các endpoint FastAPI cho Streamlit UI."""

import httpx


class ApiClientError(RuntimeError):
    """Lỗi khi giao tiếp với FastAPI backend."""


def _extract_error_detail(response: httpx.Response) -> str:
    """Trích thông điệp lỗi dễ đọc từ JSON phản hồi của FastAPI."""
    try:
        payload = response.json()
        if isinstance(payload, dict) and payload.get("detail"):
            return str(payload["detail"])
    except ValueError:
        pass
    text = response.text.strip()
    return text or f"HTTP {response.status_code}"


def check_api_health(base_url: str, timeout: float = 5.0) -> bool:
    """Kiểm tra nhanh trạng thái sẵn sàng của API."""
    url = f"{base_url.rstrip('/')}/api/v1/healthz"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)
            return response.status_code == 200
    except httpx.HTTPError:
        return False


def upload_contract_file(
    base_url: str,
    file_name: str,
    content: bytes,
    content_type: str | None = None,
    client: httpx.Client | None = None,
) -> dict:
    """Gửi file hợp đồng lên POST /api/v1/contracts/upload."""
    url = f"{base_url.rstrip('/')}/api/v1/contracts/upload"
    mime = content_type or "application/octet-stream"
    files = {"file": (file_name, content, mime)}
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)

    try:
        if client is not None:
            response = client.post(url, files=files, timeout=timeout)
        else:
            with httpx.Client(timeout=timeout) as local_client:
                response = local_client.post(url, files=files)
    except httpx.HTTPError as error:
        raise ApiClientError(f"Không thể kết nối tới API ({url}): {error}") from error

    if response.status_code >= 400:
        raise ApiClientError(
            f"Upload thất bại ({response.status_code}): {_extract_error_detail(response)}"
        )
    return response.json()


def trigger_audit_process(
    base_url: str,
    contract_id: int,
    client: httpx.Client | None = None,
) -> dict:
    """Kích hoạt xử lý nền qua POST /api/v1/audit/process/{contract_id}."""
    url = f"{base_url.rstrip('/')}/api/v1/audit/process/{contract_id}"
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

    try:
        if client is not None:
            response = client.post(url, timeout=timeout)
        else:
            with httpx.Client(timeout=timeout) as local_client:
                response = local_client.post(url)
    except httpx.HTTPError as error:
        raise ApiClientError(f"Không thể kết nối tới API khi kích hoạt xử lý: {error}") from error

    if response.status_code >= 400:
        raise ApiClientError(
            f"Không thể bắt đầu xử lý ({response.status_code}): {_extract_error_detail(response)}"
        )
    return response.json()


def fetch_audit_result(
    base_url: str,
    contract_id: int,
    include_trace: bool = True,
    client: httpx.Client | None = None,
) -> dict:
    """Lấy trạng thái và kết quả thẩm định từ GET /api/v1/audit/result/{contract_id}."""
    url = f"{base_url.rstrip('/')}/api/v1/audit/result/{contract_id}"
    params = {"include_trace": "true" if include_trace else "false"}
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

    try:
        if client is not None:
            response = client.get(url, params=params, timeout=timeout)
        else:
            with httpx.Client(timeout=timeout) as local_client:
                response = local_client.get(url, params=params)
    except httpx.HTTPError as error:
        raise ApiClientError(f"Lỗi kết nối khi kiểm tra kết quả: {error}") from error

    if response.status_code >= 400:
        raise ApiClientError(
            f"Không lấy được kết quả ({response.status_code}): {_extract_error_detail(response)}"
        )
    return response.json()
