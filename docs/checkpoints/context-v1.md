# Checkpoint evidence — `context-v1`

| Thuộc tính | Giá trị |
| --- | --- |
| Ngày nghiệm thu | `01/09/2026` |
| Gate | `W2 = PASS` |
| Scenario | `COMPUTE_DOWN / compute-01` |
| Phạm vi | Aggregate mock, read-only Recovery Context |
| OpenStack Lab Readiness | `BLOCKED_EXTERNAL` — không thuộc Gate W2 |

## Artifact được nghiệm thu

- FastAPI app có lifespan load-once, `POST /incidents`, `/healthz` và OpenAPI.
- Pydantic v2 models strict/frozen; fixture schema/reference/capacity fail fast.
- `NetBoxService` và `IncidentService` chỉ đọc, deterministic, không mutate fixture.
- Error envelope và `X-Correlation-ID` được chuẩn hóa.
- Không có database, planner, application graph, OpenStack SDK hoặc write path.

## Môi trường kiểm tra

```text
Architecture: arm64
Python:       3.13.7
FastAPI:      0.141.1
Pydantic:     2.13.5
Uvicorn:      0.52.4
pytest:       9.1.1
httpx:        0.28.1
```

Dependencies được cài từ `dr-system/pyproject.toml` bằng editable install trong
một virtualenv tạm sạch.

## Test evidence

Lệnh:

```bash
python -B -m pytest -q -p no:cacheprovider
```

Kết quả:

```text
..............................................                           [100%]
46 passed, 1 warning in 0.24s
```

Warning duy nhất là deprecation warning từ FastAPI/Starlette TestClient về quá
trình chuyển đổi thư viện test HTTP; không phát sinh từ domain/API code và không
ảnh hưởng kết quả. Test suite bao phủ:

| ID | Evidence chính |
| --- | --- |
| CTX-001 | Context đúng rack/AZ, VM và candidate deterministic |
| CTX-002 | Unknown compute trả `404 RESOURCE_NOT_FOUND` |
| CTX-003 | `RACK_DOWN` trả `422 UNSUPPORTED_INCIDENT_TYPE` |
| CTX-004 | Payload thiếu/sai/blank trả `422 VALIDATION_ERROR` |
| CTX-005 | Source luôn bị loại khỏi candidate pool |
| CTX-006 | Compute down/disabled/exhausted bị loại |
| CTX-007 | VM reference sai làm startup fail fast |
| CTX-008 | Request lặp cho cùng output và fixture không bị mutate |

Các test bổ sung xác minh malformed JSON, schema version, timezone, extra field,
duplicate compute/VM, negative/over-allocated resource, `/healthz`, OpenAPI,
correlation ID, load-once lifespan và sanitized `500 INTERNAL_ERROR`.

## Uvicorn/curl smoke evidence

Backend được khởi động bằng:

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 8765
```

Request thực tế trả `HTTP/1.1 200 OK`, giữ
`X-Correlation-ID: smoke-context-001` và body:

```json
{
  "incident": {"type": "COMPUTE_DOWN", "resource": "compute-01"},
  "affected_vms": ["vm-api-01", "vm-web-01"],
  "source": {"az": "AZ-01", "rack": "rack-01"},
  "available_compute": ["compute-05", "compute-06"]
}
```

## Gate W2

Toàn bộ checklist DoD Checkpoint 1 tại `plan_full.md` đã đạt. Checkpoint được
gắn nhãn tài liệu `context-v1`; không tạo Git commit hoặc tag. W3 chỉ được mở với
Persistence + Application-aware Impact + Candidate Filter, còn real OpenStack
tiếp tục bị chặn tới khi P01–P09 có evidence.
