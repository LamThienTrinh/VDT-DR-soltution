# DR Recovery Context — Checkpoint `context-v1`

Backend read-only đầu tiên của OpenStack DR Orchestrator. Checkpoint này nhận một
incident `COMPUTE_DOWN`, đọc aggregate fixture local và trả về source failure
domain, các VM bị ảnh hưởng cùng preliminary candidate pool.

Checkpoint **không** có database, planner, application graph, OpenStack SDK hoặc
bất kỳ write action nào ra hạ tầng.

## Yêu cầu

- Python `>=3.11,<3.14`
- `pip`

## Cài đặt

Từ thư mục `dr-system/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Chạy backend

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Sau khi startup thành công:

- Health check: `http://127.0.0.1:8000/healthz`
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI schema: `http://127.0.0.1:8000/openapi.json`

Fixture `data/netbox_mock.json` được đọc và validate đúng một lần trong FastAPI
lifespan. Nếu JSON, schema hoặc VM-to-compute reference sai, startup dừng với
`INVALID_TOPOLOGY_SNAPSHOT` thay vì phục vụ context không đáng tin cậy.

## Gọi API

```bash
curl --silent --show-error \
  --request POST http://127.0.0.1:8000/incidents \
  --header 'Content-Type: application/json' \
  --header 'X-Correlation-ID: demo-context-001' \
  --data '{"type":"COMPUTE_DOWN","resource":"compute-01"}'
```

Expected response (`200 OK`):

```json
{
  "incident": {
    "type": "COMPUTE_DOWN",
    "resource": "compute-01"
  },
  "affected_vms": [
    "vm-api-01",
    "vm-web-01"
  ],
  "source": {
    "az": "AZ-01",
    "rack": "rack-01"
  },
  "available_compute": [
    "compute-05",
    "compute-06"
  ]
}
```

`available_compute` chỉ là candidate pool sơ bộ: compute phải khác source, ở
trạng thái `UP`, được enable và còn dương ở cả VCPU, RAM và disk. Checkpoint này
chưa chọn placement target cho từng VM.

## Error contract

Mọi HTTP error dùng envelope ổn định:

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "compute 'compute-404' was not found",
    "correlation_id": "demo-context-001"
  }
}
```

| Trường hợp | HTTP | `error.code` |
| --- | ---: | --- |
| Payload thiếu, sai type dữ liệu hoặc chuỗi rỗng | 422 | `VALIDATION_ERROR` |
| Incident type khác `COMPUTE_DOWN` | 422 | `UNSUPPORTED_INCIDENT_TYPE` |
| Compute không tồn tại | 404 | `RESOURCE_NOT_FOUND` |
| Lỗi nội bộ không dự kiến | 500 | `INTERNAL_ERROR` |

Header `X-Correlation-ID` hợp lệ theo `[A-Za-z0-9._-]{1,128}` được giữ nguyên;
giá trị thiếu hoặc không hợp lệ được thay bằng UUID và luôn trả lại trong
response header.

## Chạy test

```bash
python -m pytest -q
```

Test suite bao phủ CTX-001…CTX-008, validation fixture, deterministic ordering,
no-mutation, error envelope, correlation ID, OpenAPI và startup fail-fast.

## Cấu trúc

```text
dr-system/
├── app.py
├── pyproject.toml
├── data/netbox_mock.json
├── models/recovery_context.py
├── services/netbox_service.py
├── services/incident_service.py
└── tests/
```
