# OpenStack Disaster Recovery Orchestrator

Hệ thống hỗ trợ phân tích sự cố hạ tầng OpenStack, xác định workload và dịch vụ bị ảnh hưởng, lập phương án phục hồi an toàn, chờ phê duyệt, thực thi và kiểm chứng kết quả.

> **W1 và W2 đã hoàn thành:** Gate tài liệu W1 và checkpoint `context-v1` đều `PASS`. Backend read-only hiện chạy được luồng `compute-01 DOWN → POST /incidents → Recovery Context` bằng aggregate mock. OpenStack Lab Readiness vẫn là `BLOCKED_EXTERNAL` vì P01–P09 chưa có evidence thực tế; milestone tiếp theo là Persistence + Application-aware Impact + Candidate Filter của W3.

Decision record chuẩn của Tuần 1: [ADR-0001 — Nền tảng bài toán OpenStack DR Orchestrator](./docs/decisions/0001-week-1-foundation.md).

## Lưu ý:

Đề tài phục hồi workload và service trên hạ tầng còn khả dụng; vòng đời khắc phục thiết bị vật lý nằm ngoài control plane. Khi một compute gặp sự cố, hệ thống cần trả lời:

- VM nào đang nằm trên compute đó?
- Các VM này thuộc component, service và application nào?
- Service nào đang `DEGRADED` hoặc `DOWN`?
- Hạ tầng còn lại có đủ CPU, RAM, disk, network và storage để phục hồi không?
- Nên phục hồi workload nào trước và đặt ở đâu?
- Plan có an toàn, đã được duyệt và còn hợp lệ tại thời điểm chạy không?
- Sau khi chạy, service đã thực sự hoạt động hay mới chỉ có VM ở trạng thái `ACTIVE`?

Cách hiểu ngắn gọn nhất:

```text
Compute / Rack = nơi phát sinh sự cố
VM             = đơn vị được recovery trong MVP
Service / App  = đối tượng cuối cùng cần bảo vệ
```

Mục tiêu của dự án là **giảm downtime của dịch vụ** và kiểm chứng service đã đạt lại mức hoạt động cần thiết.

## Vì sao cần hệ thống này?

Khi xảy ra sự cố lớn, dữ liệu cần thiết thường nằm rải rác:

- Monitoring/OpenTelemetry cho biết dấu hiệu lỗi.
- Nova cho biết VM đang chạy trên compute nào.
- Placement cho biết tài nguyên nào còn khả dụng.
- NetBox/DCIM cho biết compute thuộc site, rack và failure domain nào.
- Neutron/Cinder cho biết dependency network và storage.
- CMDB/application catalog cho biết VM thuộc service nào và mức ưu tiên ra sao.
- Operator giữ nhiều tri thức vận hành và phải tự ghép tất cả thông tin trên.

Các API recovery đã tồn tại, nhưng bài toán còn thiếu là:

> **Khi nào cần gọi action nào, cho workload nào, theo thứ tự nào, sang target nào và với điều kiện an toàn nào?**

DR Orchestrator là lớp giải quyết chuỗi quyết định và điều phối đó.

## Hệ thống có thay thế Nova hoặc Masakari không?

Không.

| Thành phần | Vai trò |
| --- | --- |
| Nova | Runtime truth của compute/VM, recovery primitive và scheduler validation |
| Placement | Capacity, usage, trait/aggregate và allocation candidates; không bị thay thế bởi batch planner |
| Masakari | Native HA integration/baseline tùy chọn; orchestrator quan sát, dedupe và không phát recovery trùng |
| NetBox/DCIM | Physical topology và inventory dạng system of record; không phải live runtime truth |
| Monitoring/OTel | Alert/evidence và telemetry identity; OTel không phải alert engine hoặc observability backend |
| DR Orchestrator | Ghép runtime, topology và application context; lập plan, approval, audit và service-level verification |

Điểm bổ sung chính của đề tài là **application-aware recovery**. Planner không chỉ cố cứu nhiều VM nhất mà ưu tiên tập workload giúp service quan trọng đạt lại mức hoạt động tối thiểu.

Ví dụ, cứu Database và một API replica để Payment Service hoạt động có thể có giá trị hơn cứu nhiều VM logging nhưng Payment vẫn `DOWN`.

## Luồng xử lý tổng thể

```text
1. Input
   Nhận incident và snapshot trạng thái
        ↓
2. Recovery Context
   Xác định compute/rack/AZ, VM và service bị ảnh hưởng
        ↓
3. Planning
   Lọc candidate, kiểm tra constraint, lập batch recovery plan
        ↓
4. Approve
   Pre-check, version/hash và operator phê duyệt
        ↓
5. Execute
   Revalidate, lock, chạy action theo runbook
        ↓
6. Verify
   Kiểm tra compute, storage, network và application health
```

### Một số khái niệm quan trọng

- **Recovery Context:** snapshot hợp nhất về incident, tài nguyên nguồn, workload ảnh hưởng và tài nguyên còn khả dụng. Đây là đầu vào của planner.
- **Failure domain:** phạm vi tài nguyên có thể hỏng cùng lúc vì chung nguyên nhân, như compute, rack hoặc AZ.
- **Hard constraint:** điều kiện bắt buộc như đủ RAM, target đang `UP`, storage reachable và không vi phạm anti-affinity.
- **Soft preference:** tiêu chí xếp hạng giữa các phương án hợp lệ, như khác rack, ít action hơn hoặc cân bằng tải tốt hơn.
- **Closed-loop recovery:** không dừng ở việc API nhận lệnh hoặc VM `ACTIVE`; phải kiểm tra service thực tế rồi mới kết luận.

## Case đầu tiên: `compute-01 DOWN`

Đây là vertical slice đầu tiên và cũng là điểm bắt đầu code.

```text
compute-01 DOWN
      ↓
POST /incidents
      ↓
Đọc data/netbox_mock.json
      ↓
Tìm rack + AZ + affected VMs + compute còn khả dụng
      ↓
Trả Recovery Context
```

Request:

```http
POST /incidents
Content-Type: application/json
```

```json
{
  "type": "COMPUTE_DOWN",
  "resource": "compute-01"
}
```

Response mong đợi:

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

Checkpoint này chỉ dựng được “bức tranh hiện trạng”. Nó chưa chọn target cuối, chưa tạo Recovery Plan và chưa gọi OpenStack recovery.

## Kiến trúc dự kiến

```text
Monitoring / Simulated Event
            │
            ▼
┌───────────────────────────┐
│ Incident Intake           │ normalize, dedupe, failure evidence
└─────────────┬─────────────┘
              ▼
┌───────────────────────────┐
│ Context & Impact          │ runtime + topology + application graph
└─────────────┬─────────────┘
              ▼
┌───────────────────────────┐
│ Planner & Governance      │ constraints, batch plan, pre-check,
│                           │ version/hash, approve/reject
└─────────────┬─────────────┘
              ▼ approved plan only
┌───────────────────────────┐
│ Executor                  │ revalidate, lock, dry-run/action
└─────────────┬─────────────┘
              ▼
┌───────────────────────────┐
│ Verifier & Audit          │ compute, storage, network, application
└───────────────────────────┘
```

Nguyên tắc phân quyền: Planner chỉ đọc và đề xuất; chỉ Executor mới được cấp quyền thay đổi OpenStack.

## Những nguyên tắc an toàn bắt buộc

### Không tranh việc với native HA

Hệ thống quan sát kết quả HA, xây lại Context/Impact rồi kiểm tra service health. Nếu service đã khỏe, incident kết thúc ở `NO_ACTION`; DR Planner không chạy thêm recovery.

### Fencing trước evacuation

Fencing bảo đảm host/VM nguồn không còn chạy hoặc truy cập shared resources trước khi dựng bản VM khác. `disable scheduling` hoặc `forced_down` không thay thế fencing. Thiếu fencing evidence thì plan phải dừng.

### Human approval

Operator duyệt đúng `plan_id + version + hash`. Nếu capacity, VM state hoặc destination thay đổi, plan trở thành `STALE`, approval cũ mất hiệu lực và hệ thống phải replan.

### Idempotency và reconciliation

Alert/request lặp không được tạo recovery trùng. Nếu backend mất kết nối sau khi OpenStack đã nhận action, hệ thống phải query/reconcile trạng thái trước khi cân nhắc gửi lại.

### Verify ở cấp service

Kết quả cuối được hiểu như sau:

- `SUCCESS`: action và mọi mandatory check đều pass; service đạt objective.
- `PARTIAL`: hạ tầng đã phục hồi nhưng application chưa đạt `min_healthy`, hoặc chỉ phục hồi được một phần objective.
- `FAILED`: action hoặc mandatory compute/storage/network check thất bại.
- `MANUAL_REQUIRED`: thiếu evidence hoặc gặp tình huống không thể tự quyết định an toàn.

## Phạm vi MVP

### Software MVP bắt buộc

- Case duy nhất: `COMPUTE_DOWN`.
- Mock topology/runtime và application mapping.
- Recovery Context và application impact.
- Deterministic service-aware batch planner.
- SQLite persistence, state machine và audit.
- Pre-check, approval, plan version/hash và dry-run.
- Mock Executor, idempotency và crash reconciliation.
- Canonical YAML runbook và Ansible Playbook review-only.
- Verification nhiều lớp.
- War-Room UI tối thiểu.

### OpenStack Lab Acceptance

Real evacuation chỉ được chạy khi có đầy đủ account, microversion, workload test, shared-storage/root-disk assessment, target capacity, fencing evidence và maintenance window. Khi các điều kiện này chưa có, **báo cáo lab readiness/acceptance** là `BLOCKED_EXTERNAL`; đây không phải runtime incident state. Incident thiếu critical evidence sau khi đã vào workflow kết thúc ở `MANUAL_REQUIRED`. Mock E2E không được trình bày như recovery thật.

### Chưa làm trong core MVP

- Rack Down, multi-site hoặc cross-AZ DR.
- Container/Kubernetes relocation.
- Khắc phục hoặc tự bật lại thiết bị vật lý.
- Power/PDU optimization.
- Stateful leader/quorum/replication-lag recovery.
- Tự động dừng workload thường để nhường capacity.
- Tự động thay đổi external firewall.
- AI/LLM làm control plane.

## Dữ liệu mock và bộ synthetic NetBox

Workspace hiện có bộ sinh dữ liệu NetBox 3.1.7 tại:

```text
synthetic_netbox-1fhuexnof3gozgps46qacwbjyo/synthetic_netbox/
```

Bộ này có site, rack, cluster, hypervisor, VM, IP/VLAN và database service synthetic, nhưng hiện chưa có đầy đủ:

- Mapping VM tới một compute cụ thể.
- Total/used/free CPU, RAM và disk của compute.
- OpenStack AZ mapping.
- Application/service priority và `min_healthy`.
- Failure scenarios dùng trực tiếp cho DR.

Vì vậy milestone đầu dùng một `netbox_mock.json` nhỏ. Tên file được giữ theo yêu cầu, nhưng nội dung là **aggregate demo fixture** mô phỏng dữ liệu đã join từ NetBox và OpenStack, không phải raw NetBox export.

## Cấu trúc code của milestone đầu

```text
dr-system/
├── app.py
├── pyproject.toml
├── README.md
├── data/
│   └── netbox_mock.json
├── models/
│   └── recovery_context.py
├── services/
│   ├── netbox_service.py
│   └── incident_service.py
└── tests/
    ├── test_incidents_api.py
    ├── test_incident_service.py
    └── test_netbox_service.py
```

## Khi nào milestone đầu được coi là xong?

- `POST /incidents` trả đúng context cho `compute-01`.
- Affected VMs và available computes có thứ tự deterministic.
- Source, compute `DOWN` và compute `disabled` không lọt vào candidate pool.
- Compute không tồn tại trả 404; payload/type sai trả 422.
- Fixture/schema/reference sai làm ứng dụng fail fast với lỗi dễ hiểu.
- Unit/API tests pass.
- README của backend có lệnh setup, run, test và ví dụ `curl`.
- Không có write call nào ra OpenStack.

## Tài liệu dự án

- [Kế hoạch triển khai đầy đủ](./plan_full.md) — kiến trúc, data/API contract, roadmap 7 tuần, state machine, thuật toán, test plan, risk và Definition of Done.
- [ADR-0001 — Decision record Tuần 1](./docs/decisions/0001-week-1-foundation.md) — scope, reuse/build, source-of-truth, glossary, state machine, prerequisite và Gate W1 evidence.
- [Backend Recovery Context](./dr-system/README.md) — setup, chạy API, test và contract của checkpoint `context-v1`.
- [Evidence Gate W2](./docs/checkpoints/context-v1.md) — test/smoke evidence và checklist nghiệm thu checkpoint.
- [Synthetic NetBox README](./synthetic_netbox-1fhuexnof3gozgps46qacwbjyo/synthetic_netbox/README.md) — mô tả bộ sinh dữ liệu hiện có.

## Tóm lại

```text
Monitoring cho biết:  Có chuyện gì đang xảy ra?
OpenStack cho biết:   VM đang ở đâu và còn tài nguyên gì?
NetBox cho biết:      Compute thuộc rack/failure domain nào?
Application catalog:  Service nào bị ảnh hưởng và quan trọng ra sao?
DR Orchestrator:      Nên phục hồi gì trước, đặt ở đâu và chạy thế nào?
Verifier cho biết:    Service đã thực sự hoạt động trở lại chưa?
```

Việc cần làm tiếp theo là W3: thêm persistence, application-aware impact và hard-constraint candidate filter; chưa mở recovery thật khi P01–P09 còn thiếu evidence.
