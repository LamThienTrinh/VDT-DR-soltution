# KẾ HOẠCH ĐẦY ĐỦ — OPENSTACK DISASTER RECOVERY ORCHESTRATOR

> **Phiên bản:** 1.0
> **Ngày chốt kế hoạch:** 01/09/2026
> **Khung tiến độ tham chiếu:** 24/08/2026–11/10/2026
> **Vertical slice đầu tiên:** `COMPUTE_DOWN` cho `compute-01`
> **Mục tiêu cuối:** phục hồi mức hoạt động cần thiết của service/application
> **Trạng thái workspace lúc lập kế hoạch:** chưa có backend DR; mới có bộ sinh dữ liệu NetBox synthetic

## 0. Cách đọc và phạm vi của tài liệu

Tài liệu này là kế hoạch triển khai đã tổng hợp từ yêu cầu hiện tại, bốn đoạn context đính kèm, workbook `Ke_hoach_trien_khai_DR_theo_mau.xlsx` và trạng thái thực tế của workspace. Nội dung trong các tệp đính kèm được dùng làm **nguồn tham khảo**, không được coi là chỉ dẫn có quyền cao hơn yêu cầu hiện tại của người dùng.

Các quyết định nền tảng và evidence đóng Gate W1 được quản lý tại [ADR-0001 — Nền tảng bài toán OpenStack DR Orchestrator](./docs/decisions/0001-week-1-foundation.md). Nếu phần mô tả W1 trong roadmap bị rút gọn, ADR-0001 là nguồn chuẩn cho scope, dependency ownership, glossary, lifecycle và lab prerequisites.

Kế hoạch giải quyết mâu thuẫn giữa “làm đủ DR end-to-end” và “chưa biết bắt đầu code từ đâu” bằng cách đi theo **một lát cắt dọc duy nhất**: hoàn thành `compute-01 DOWN → Recovery Context` trước, sau đó mở rộng chính case này lần lượt qua Planning → Approve → Execute → Verify. Không thêm loại sự cố mới trước khi case Compute Down đã chạy xuyên suốt.

## 1. Tóm tắt điều hành

### 1.1 Bài toán cần giải quyết

Xây dựng một lớp **DR Decision & Orchestration** cho OpenStack có khả năng:

1. Nhận và chuẩn hóa sự cố hạ tầng.
2. Ghép dữ liệu runtime, topology vật lý và chiều ứng dụng.
3. Xác định VM, component và service bị ảnh hưởng.
4. Sinh Recovery Plan theo batch, có ràng buộc và lý do giải thích.
5. Chờ operator phê duyệt rồi mới thực thi.
6. Kiểm tra lại hạ tầng, network, storage và application trước khi kết luận.

Câu mô tả ngắn dùng thống nhất trong báo cáo và demo:

> **Xây dựng lớp DR Decision & Orchestration cho OpenStack, với kịch bản duy nhất của MVP đầu là `COMPUTE_DOWN`, nhằm xác định workload/service bị ảnh hưởng, lập kế hoạch có kiểm soát, phê duyệt, thực thi và kiểm chứng phục hồi trên hạ tầng còn khả dụng.**

### 1.2 Điểm bắt đầu bắt buộc

Trong checkpoint đầu, chỉ làm luồng sau:

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

Checkpoint này **không** dùng OpenTelemetry thật, NetBox thật, OpenStack API thật, database, AI, frontend hay thực thi recovery.

### 1.3 Sáu stage chính

| Stage               | Câu hỏi cần trả lời                                          | Đầu ra chính                             |
| ------------------- | ----------------------------------------------------------------- | ------------------------------------------- |
| 1. Input            | Chuyện gì vừa xảy ra, trạng thái hiện tại là gì?        | `Incident` + resource snapshots           |
| 2. Recovery Context | Compute/VM/service nào bị ảnh hưởng, còn tài nguyên nào? | `RecoveryContext`                         |
| 3. Planning         | Khôi phục workload nào trước và đặt ở đâu?             | `RecoveryPlan` có reason/risk            |
| 4. Approve          | Plan đã an toàn và được ai duyệt?                         | `ApprovalRecord` gắn version/hash        |
| 5. Execute          | Gọi action nào, thứ tự nào, có chạy trùng không?         | `ExecutionResult` + audit timeline        |
| 6. Verify           | Service đã thực sự hoạt động trở lại chưa?              | `VerificationResult` + trạng thái cuối |

## 2. Bản chất đề tài và ranh giới trách nhiệm

### 2.1 HA, DR và ranh giới phục hồi workload

> **Lý thuyết ngắn — HA và DR:** High Availability dùng redundancy/failover để giữ dịch vụ liên tục trước các lỗi đã dự kiến. Trong phạm vi đề tài này, Disaster Recovery được kích hoạt khi service vẫn suy giảm hoặc ngừng hoạt động sau cửa sổ quan sát native HA, chẳng hạn do thiếu capacity hoặc lỗi nhiều failure domain. Service đã healthy thì kết thúc với `NO_ACTION`.

Hệ thống không tham gia vòng đời khắc phục nguồn, RAM, mainboard, switch hoặc rack vật lý. Nếu `compute-01` chết, mục tiêu là cô lập host lỗi và khôi phục workload/service phụ thuộc vào nó. Workflow health-check và re-enable compute sau khi thiết bị được xử lý là phần mở rộng, không phải core MVP.

| Đối tượng                 | Vai trò trong đề tài                                                  |
| ----------------------------- | ------------------------------------------------------------------------- |
| Compute/Rack/AZ               | Nơi phát sinh lỗi hoặc failure domain                                 |
| VM                            | Recovery unit của MVP — đơn vị được restart/rebuild/evacuate      |
| Component/Service/Application | Protected object — mục tiêu nghiệp vụ cần phục hồi                |
| Operator                      | Người kiểm tra, phê duyệt và chịu trách nhiệm cho action rủi ro |

> **Lý thuyết ngắn — recovery unit và recovery objective:** MVP thao tác qua OpenStack VM nên VM là recovery unit. Tuy nhiên mục tiêu là đưa service về mức hoạt động tối thiểu; không nhất thiết phục hồi mọi VM nếu một tập component nhỏ hơn đã đủ làm service healthy.

> **Lý thuyết ngắn — failure domain và blast radius:** Failure domain là phạm vi có thể hỏng đồng thời do chung nguyên nhân, ví dụ host, rack, AZ hoặc nguồn điện. Blast radius là tập resource và service bị ảnh hưởng bởi lỗi đó; `compute-01` tạo blast radius trực tiếp lên các VM của nó rồi gián tiếp lên application graph.

### 2.2 Khoảng trống so với các thành phần sẵn có

Không nên tuyên bố “OpenStack chưa làm recovery”. Các thành phần hiện có giải quyết nhiều primitive quan trọng; đóng góp của đề tài nằm ở lớp quyết định và quy trình khép kín.

| Thành phần                   | Đã làm tốt                                                                               | Phần đề tài bổ sung                                                                                              |
| ------------------------------ | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Nova Scheduler/Placement       | Xác minh resource provider/candidate, resource inventory, trait và allocation              | Lập kế hoạch theo batch nhiều VM, failure domain vật lý, service priority, explainability và approval          |
| Masakari                       | VMHA/host-failure detection và recovery workflow; có failover segment và recovery methods | Application graph, service-aware objective, checklist network/firewall, human approval và service-level verification |
| Watcher                        | Optimization/action plan cho các use case tối ưu/bảo trì hạ tầng                      | Incident-driven DR pipeline và xác minh service sau recovery                                                        |
| NetBox/DCIM                    | System of record cho site/location/rack/device/cluster/VM/IP                                 | Không phải live monitoring; cần join với Nova runtime và application catalog                                     |
| OpenTelemetry/Monitoring       | Telemetry để biết điều gì đang xảy ra                                                | Không phải recovery engine hay CMDB; orchestrator dùng identity để correlate                                     |
| DR Orchestrator của đề tài | —                                                                                           | Ghép tất cả context, quyết định, kiểm soát, thực thi và verify closed loop                                  |

Nova định nghĩa `evacuate` là dựng lại server trên compute khác khi host nguồn hỏng; host nguồn phải được fence và Nova không tự làm fencing. Placement trả allocation candidates theo capacity/trait/aggregate, còn snapshot đó vẫn phải được revalidate trước execute. Masakari nên được dùng làm baseline hoặc adapter tích hợp, không phải đối tượng để phủ nhận. Xem [Nova failed-compute recovery](https://docs.openstack.org/api-guide/compute/server_concepts.html#recover-from-a-failed-compute-host), [Nova evacuate API](https://docs.openstack.org/api-ref/compute/#evacuate-server-evacuate-action), [Placement allocation candidates](https://docs.openstack.org/api-ref/placement/#allocation-candidates) và [Masakari failover segments](https://docs.openstack.org/api-ref/instance-ha/#failoversegments-segments).

### 2.3 Điểm mới/đóng góp của đề tài

Đóng góp được chốt thành bốn ý, theo thứ tự ưu tiên:

1. **Unified Recovery Context:** hợp nhất runtime OpenStack, topology rack/AZ và application mapping thành một snapshot có thể audit/replay.
2. **Service-aware batch planning:** không tối đa số VM được cứu; ưu tiên tập workload nhỏ nhất có thể đưa service quan trọng trở lại.
3. **Safe orchestration:** pre-check, version/hash, human approval, revalidation, fencing gate, idempotency và audit.
4. **Closed-loop verification:** chỉ kết luận thành công khi các kiểm tra bắt buộc ở tầng compute, storage, network và application đều đạt.

> **Lý thuyết ngắn — DR orchestration:** Nova, Neutron và Cinder cung cấp primitive để thao tác tài nguyên. Orchestrator là lớp phối hợp toàn chuỗi phát hiện → phân tích → lập plan → duyệt → thực thi → kiểm chứng, đồng thời quyết định thứ tự và điều kiện an toàn để gọi các primitive đó.

## 3. Phạm vi đã chốt

### 3.1 Checkpoint 1 — Recovery Context nhỏ nhất

**In scope:**

- Một incident type: `COMPUTE_DOWN`.
- Một fixture chính: `compute-01` ở `rack-01`, `AZ-01`.
- Hai VM ảnh hưởng: `vm-web-01`, `vm-api-01`.
- Hai compute khả dụng mong đợi: `compute-05`, `compute-06`.
- FastAPI endpoint `POST /incidents`.
- Dữ liệu JSON local, model typed, unit/API tests và README chạy thử.

**Out of scope:**

- Không persistence incident.
- Không monitoring/OTel thật.
- Không NetBox REST.
- Không gọi Nova/Placement/Neutron/Cinder.
- Không planner placement và không action recovery.
- Không frontend.

### 3.2 MVP end-to-end

Sau khi Checkpoint 1 đạt gate, mở rộng **chính case Compute Down** với:

- Application mapping `Application → Service → Component → VM` và reverse lookup từ VM bị ảnh hưởng.
- Service priority, `min_healthy` và dependency đơn giản.
- Candidate filtering và batch placement deterministic.
- Versioned Recovery Plan, pre-check và approve/reject.
- SQLite persistence, mock executor, dry-run và runbook YAML là phần bắt buộc.
- Real OpenStack read-only adapter là mục tiêu tích hợp bắt buộc nếu có endpoint/account; real write/evacuation có acceptance gate riêng phụ thuộc lab.
- Verification nhiều lớp và audit timeline.
- War-Room UI tối thiểu phục vụ demo.

Hai mức nghiệm thu được tách rõ:

- **Software MVP bắt buộc trong 7 tuần:** full mock/dry-run E2E, persistence/audit, generated runbook, verification và War-Room UI tối thiểu. Hoàn thành mức này **không được tuyên bố** là đã recovery OpenStack thật.
- **OpenStack Lab Acceptance:** read-only discovery và một real evacuation E2E chỉ đạt khi P01–P09 được cung cấp. Nếu prerequisite bên ngoài thiếu, báo cáo readiness/acceptance là `BLOCKED_EXTERNAL` kèm evidence; đây không phải runtime incident state và không tính là real-lab DoD đã đạt.

### 3.3 Ngoài core MVP

- Rack Down, multi-compute simultaneous failure, cross-AZ/multi-site.
- Container/Kubernetes relocation.
- Khắc phục hoặc tự bật lại thiết bị vật lý.
- Power/PDU optimization.
- Tự động preempt/stop workload production ít quan trọng.
- AI/LLM tự quyết định plan hoặc trực tiếp điều khiển OpenStack.
- Dependency graph application phức tạp.
- Stateful leader/quorum/replication-lag recovery; MVP dùng workload stateless hoặc replica-equivalent cho phép kiểm tra bằng `min_healthy`.
- Tự động thay đổi network/storage dependency ngoài OpenStack.
- Reserved DR pool production-grade.
- Host maintenance/drain khi compute còn sống và repaired-host re-enable; đây là workflow mở rộng khác dead-host evacuation.
- Tự động thay đổi external firewall hoặc sinh Terraform production-ready.

> **Lý thuyết ngắn — reserved và shared capacity:** Reserved pool bảo đảm chỗ phục hồi nhưng để một phần tài nguyên nhàn rỗi; shared pool tận dụng tốt hơn nhưng có thể không còn chỗ khi sự cố. Đề tài dùng shared capacity làm scenario nghiên cứu chính và chỉ xem reserved pool là baseline/extension.

## 4. Các quyết định kiến trúc đã chốt

| ID     | Quyết định                                                                                                                         | Lý do                                                                                           |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| ADR-01 | Mục tiêu là service/application; VM là recovery unit                                                                              | Bám đúng yêu cầu vận hành nhưng giữ scope triển khai được                           |
| ADR-02 | Chỉ`COMPUTE_DOWN` cho vertical slice và MVP đầu                                                                                 | Một case đủ đi xuyên pipeline, tránh scope creep                                           |
| ADR-03 | JSON mock nhỏ trước, bộ synthetic lớn dùng sau                                                                                  | Dataset hiện tại chưa có VM→compute và free capacity rõ ràng                             |
| ADR-04 | OpenStack là runtime truth; NetBox bổ sung topology                                                                                 | Tránh dùng dữ liệu DCIM stale để suy luận live state                                      |
| ADR-05 | Application mapping thuộc catalog/policy riêng                                                                                      | NetBox/OpenStack không mặc nhiên biết chiều application                                     |
| ADR-06 | Planner deterministic/rule-based trước AI                                                                                           | Dễ test, audit, giải thích và so sánh                                                       |
| ADR-07 | Greedy heuristic là implementation đầu                                                                                             | Nhanh và dễ hoàn thành; MILP/CP-SAT là baseline/extension                                   |
| ADR-08 | Planner read-only; Executor mới có quyền write                                                                                     | Giảm blast radius và tách trách nhiệm rõ                                                   |
| ADR-09 | Dry-run mặc định; real execute chỉ trên allowlisted lab                                                                          | Bảo đảm an toàn trong quá trình phát triển/demo                                          |
| ADR-10 | Checklist runtime dùng YAML/DB, không dùng Excel                                                                                   | Machine-readable, versionable và kiểm thử được                                             |
| ADR-11 | Nếu native HA đã làm service healthy thì`NO_ACTION`                                                                            | Không tranh việc hoặc tạo race với Masakari/operator                                        |
| ADR-12 | Thiếu capacity trong MVP trả partial/unplaced, không preempt                                                                       | Preemption có blast radius lớn, cần policy/approval riêng                                    |
| ADR-13 | SQLite + SQLAlchemy/Alembic từ tuần 3; PostgreSQL là hậu MVP                                                                      | Đủ transaction/persistence cho lifecycle mà không tăng vận hành lab                       |
| ADR-14 | YAML là canonical runbook và Software MVP phải sinh thêm Ansible Playbook review-only; Terraform không dùng cho incident action | Đáp ứng deliverable runbook đúng định dạng mà vẫn tránh IaC state conflict/auto-apply |
| ADR-15 | Checklist chỉ kiểm toán firewall; thay đổi firewall là proposed/manual action cần duyệt                                       | Tách kiểm tra khỏi mutation có blast radius                                                  |

## 5. Nguồn dữ liệu và quyền sở hữu sự thật

### 5.1 Source-of-truth matrix

| Dữ liệu                            | Nguồn mock đầu tiên                       | Nguồn thật sau này                   | Quy tắc                                                        |
| ------------------------------------ | --------------------------------------------- | --------------------------------------- | --------------------------------------------------------------- |
| Compute live state, enabled/disabled | `netbox_mock.json`                          | Nova service/hypervisor                 | Nova là runtime truth                                          |
| VM đang ở compute nào             | `netbox_mock.json`                          | Nova all-project servers/extended attrs | Không suy luận chỉ từ cluster NetBox                        |
| CPU/RAM/disk còn lại               | `netbox_mock.json`                          | Placement + Nova inventory/usage        | Snapshot phải có timestamp                                    |
| Site/rack/location                   | `netbox_mock.json`                          | NetBox/DCIM                             | Unknown topology là warning/block tùy policy                  |
| OpenStack AZ                         | field`az` trong mock                        | Nova AZ + mapping NetBox custom field   | Không giả định NetBox có object AZ chuẩn                  |
| Network/port/SG                      | field mock tối thiểu                        | Neutron                                 | Re-query trước execute                                        |
| Volume/storage                       | field mock tối thiểu                        | Cinder + storage policy                 | Phải ghi loại root disk/data-loss risk                        |
| App/component/service                | `application_mock.json` hoặc cùng fixture | CMDB/service catalog/policy DB          | Có version và owner                                           |
| Alert/telemetry                      | request giả lập                             | Alertmanager/monitoring/OTel            | OTel là telemetry transport/context, không phải alert engine |
| Priority/RTO/checklist               | config YAML                                   | Policy DB/CMDB                          | Không lấy alpha telemetry attribute làm authority duy nhất  |

NetBox mô hình được site/location/rack/device/cluster/VM và có thể pin VM vào host device, nhưng là infrastructure system of record chứ không phải live monitoring. OpenTelemetry cung cấp trace/metric/log và identity như `service.name`, `service.instance.id`, `host.id`, `cloud.availability_zone`; rack nên enrich từ NetBox. Xem [NetBox virtualization](https://netboxlabs.com/docs/netbox/features/virtualization/), [NetBox VM model](https://netboxlabs.com/docs/netbox/models/virtualization/virtualmachine/), [OpenTelemetry resources](https://opentelemetry.io/docs/specs/otel/resource/) và [service semantic conventions](https://opentelemetry.io/docs/specs/semconv/resource/service/).

### 5.2 Đánh giá bộ synthetic NetBox hiện có

Tài sản hiện có tại `synthetic_netbox-1fhuexnof3gozgps46qacwbjyo/synthetic_netbox/`:

- Generator NetBox 3.1.7 có seed cố định `20260826`.
- Có 5 site, rack, cluster, hypervisor, VM, IP/VLAN và database service synthetic.
- Có hard-case metadata cho legacy/vulnerable/runtime failure, hữu ích cho test sau.
- Có thể scale tới dataset lớn để stress test collector/planner.

Khoảng trống phải đóng trước khi dùng cho Compute Down:

- Chưa có `netbox_mock.json` sẵn.
- Tên object không theo fixture demo `compute-01`, `vm-web-01`.
- VM hiện gắn với cluster, chưa có mapping rõ tới một hypervisor cụ thể.
- Compute chưa có total/used/free CPU/RAM/disk, enabled/maintenance/headroom.
- Chưa có AZ mapping, service priority, `min_healthy`, dependency hoặc failure scenarios.
- Generator dùng cluster type synthetic vSphere, chưa đồng nhất với narrative OpenStack.

Do đó **không thay đổi generator ở Checkpoint 1**. Tạo fixture JSON nhỏ, xác minh contract trước; chỉ mở rộng generator sau khi contract ổn định.

Tên `netbox_mock.json` được giữ theo yêu cầu ban đầu, nhưng nội dung của nó là **aggregate demo fixture** mô phỏng kết quả đã join giữa topology NetBox và runtime OpenStack; không phải raw export từ NetBox. Khi tích hợp thật, tách `TopologyProvider` và `RuntimeProvider` thành hai adapter/snapshot độc lập.

## 6. Kiến trúc logic

```text
Monitoring / Simulated Event
            │
            ▼
┌──────────────────────────────┐
│ M1. Incident Intake          │ normalize, dedupe, HA evidence
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ M2. Context & Impact         │ runtime + topology + app graph
└──────────────┬───────────────┘
               ▼ service-health/native-HA gate
┌──────────────────────────────┐
│ M3. Planner & Governance     │ constraints, batch, precheck,
│                              │ version/hash, approve/reject
└──────────────┬───────────────┘
               ▼ approved plan only
┌──────────────────────────────┐
│ M4. Executor                 │ revalidate, lock, dry-run/action
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ M5. Verifier & Audit         │ compute/storage/network/app
└──────────────────────────────┘

Adapters: Mock JSON │ Nova/Placement │ NetBox │ Neutron │ Cinder │ OTel
```

Ánh xạ với cách gọi module trong các context cũ:

| Sáu stage         | Module logic trong tài liệu này | Cách gọi trong context M3/M4 |
| ------------------ | ---------------------------------- | ------------------------------ |
| Input              | M1 Incident Intake                 | Input/Detection                |
| Recovery Context   | M2 Context & Impact                | Phần đầu M3                 |
| Planning + Approve | M3 Planner & Governance            | M3                             |
| Execute            | M4 Executor                        | Phần đầu M4                 |
| Verify             | M5 Verifier & Audit                | Verifier submodule của M4     |

Việc tách M5 chỉ là tách trách nhiệm trong code; không thay đổi pipeline hoặc phạm vi đã chốt với người hướng dẫn.

### 6.1 M1 — Incident Intake

Trách nhiệm:

- Validate/normalize request.
- Tạo fingerprint và deduplicate event.
- Xác minh compute failure bằng nguồn runtime khi tích hợp thật.
- Ghi native-HA status/evidence và observation window; chưa tự kết luận service healthy khi chưa có application context.

### 6.2 M2 — Recovery Context và Impact Analysis

Trách nhiệm:

- Snapshot compute nguồn, rack, AZ, affected VMs và remaining candidates.
- Join `VM → Component → Service → Application`.
- Tính `healthy_replicas`, `min_healthy`, `missing_replicas` và service state.
- Gắn evidence, source versions và timestamps để audit/replay.
- Sau khi có service health, áp dụng native-HA gate: nếu service healthy thì `NO_ACTION`; nếu còn degraded/down thì chuyển sang Planning.

Ở Checkpoint 1 chưa có application graph nên chưa kết luận native HA ở cấp service; endpoint chỉ dựng context hạ tầng. Từ tuần 3, `ServiceHealthProvider` và application mapping cung cấp evidence cho gate này.

### 6.3 M3 — Recovery Planning, Pre-check và Approval

Trách nhiệm:

- Nhận immutable `RecoveryContext`.
- Lọc hard constraints, xếp hạng soft preferences.
- Lập batch plan theo service priority/minimum viable service.
- Sinh rejected-candidate reasons, risk, fallback và unplaced deficits.
- Chạy pre-check, version/hash plan, submit/approve/reject.
- **Không có credential write OpenStack.**

### 6.4 M4 — Executor

Trách nhiệm:

- Chỉ nhận plan đúng version ở trạng thái `APPROVED`.
- Revalidate snapshot ngay trước execute.
- Acquire execution lock và kiểm tra idempotency.
- Xác nhận fencing trước evacuation.
- Gọi adapter theo thứ tự và theo dõi asynchronous action.
- Retry/backoff giới hạn; không tự ý đổi plan đã duyệt.

### 6.5 M5 — Verification và Audit

Trách nhiệm:

- Verify Nova state/host/task state.
- Verify Cinder attachment và data marker/checksum khi có.
- Verify Neutron port/binding/fixed IP/security group.
- Verify TCP/HTTP/application health và số replica tối thiểu.
- Tổng hợp `SUCCESS`, `PARTIAL`, `FAILED` hoặc `MANUAL_REQUIRED`, sau đó replan/escalate nếu cần.

> **Lý thuyết ngắn — closed-loop recovery:** HTTP `202 Accepted` chỉ cho biết API nhận lệnh; VM `ACTIVE` cũng chưa chứng minh service hoạt động. Closed loop tiếp tục kiểm tra storage, network, TCP/HTTP và service health rồi mới kết luận incident.

## 7. Cấu trúc project

### 7.1 Cấu trúc bắt buộc ở Checkpoint 1

```text
dr-system/
├── app.py
├── pyproject.toml
├── README.md
├── data/
│   └── netbox_mock.json
├── models/
│   ├── __init__.py
│   └── recovery_context.py
├── services/
│   ├── __init__.py
│   ├── netbox_service.py
│   └── incident_service.py
└── tests/
    ├── test_incidents_api.py
    ├── test_incident_service.py
    └── test_netbox_service.py
```

Checkpoint đầu giữ cấu trúc nhỏ để nhìn được luồng. Không thêm repository pattern, message broker, PostgreSQL hoặc Kubernetes trước khi endpoint đầu tiên pass.

### 7.2 Cấu trúc mục tiêu sau khi MVP lớn dần

```text
dr-system/
├── app.py
├── api/
│   ├── incidents.py
│   ├── plans.py
│   ├── executions.py
│   └── checks.py
├── models/
│   ├── incident.py
│   ├── recovery_context.py
│   ├── recovery_plan.py
│   ├── execution.py
│   └── verification.py
├── services/
│   ├── incident_service.py
│   ├── context_service.py
│   ├── impact_service.py
│   ├── approval_service.py
│   └── audit_service.py
├── db/
│   ├── session.py
│   └── migrations/
├── repositories/
│   ├── incidents.py
│   ├── plans.py
│   └── executions.py
├── planner/
│   ├── constraints.py
│   ├── greedy.py
│   ├── scoring.py
│   └── explain.py
├── checks/
│   ├── prechecks.py
│   └── verifiers.py
├── runbooks/
│   ├── schema.py
│   └── export_ansible.py
├── adapters/
│   ├── protocols.py
│   ├── mock/
│   ├── openstack/
│   ├── netbox/
│   └── telemetry/
├── policies/
│   ├── recovery_policy.yaml
│   └── application_checks.yaml
├── data/
├── web/
│   ├── templates/
│   └── static/
├── tools/
│   └── generate_dr_scenarios.py
├── tests/
└── docs/
```

## 8. Data contract Checkpoint 1

### 8.1 Incident request tối thiểu

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

Quy ước:

- `type` hiện chỉ chấp nhận `COMPUTE_DOWN`.
- `resource` là compute name chuẩn hóa, không nhận chuỗi rỗng.
- Checkpoint 1 không tạo persistent incident nên trả `200 OK`; lifecycle `201 Created` chỉ bắt đầu ở `/api/v2/incidents` từ tuần 3.
- Khi mở rộng, alert origin dùng tên `reported_by`, tránh nhầm với field `source` đang biểu diễn vị trí hạ tầng.

### 8.2 Recovery Context response v1

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

`available_compute` ở version 1 là **candidate pool sơ bộ**, chưa phải kết quả placement. Một compute được liệt kê khi `UP`, `enabled`, không phải source, mọi dimension thỏa `0 <= allocated <= capacity`, và remaining `vcpu`, `ram_mb`, `disk_gb` đều lớn hơn 0. Planner ở stage sau mới kiểm tra toàn bộ batch/network/storage/anti-affinity. Các mảng tên trong response được sắp xếp tăng dần theo tên để contract deterministic; vì vậy `affected_vms` trả `vm-api-01` trước `vm-web-01`.

### 8.3 Mock schema tối thiểu

```json
{
  "schema_version": "1.0",
  "snapshot_at": "2026-09-01T09:00:00+07:00",
  "computes": [
    {
      "name": "compute-01",
      "status": "DOWN",
      "enabled": false,
      "az": "AZ-01",
      "rack": "rack-01",
      "capacity": {"vcpu": 32, "ram_mb": 65536, "disk_gb": 1000},
      "allocated": {"vcpu": 6, "ram_mb": 12288, "disk_gb": 120}
    },
    {
      "name": "compute-05",
      "status": "UP",
      "enabled": true,
      "az": "AZ-01",
      "rack": "rack-05",
      "capacity": {"vcpu": 32, "ram_mb": 65536, "disk_gb": 1000},
      "allocated": {"vcpu": 16, "ram_mb": 32768, "disk_gb": 400}
    },
    {
      "name": "compute-06",
      "status": "UP",
      "enabled": true,
      "az": "AZ-02",
      "rack": "rack-06",
      "capacity": {"vcpu": 32, "ram_mb": 65536, "disk_gb": 1000},
      "allocated": {"vcpu": 12, "ram_mb": 24576, "disk_gb": 300}
    }
  ],
  "vms": [
    {
      "name": "vm-web-01",
      "compute": "compute-01",
      "status": "ACTIVE",
      "resources": {"vcpu": 2, "ram_mb": 4096, "disk_gb": 40}
    },
    {
      "name": "vm-api-01",
      "compute": "compute-01",
      "status": "ACTIVE",
      "resources": {"vcpu": 4, "ram_mb": 8192, "disk_gb": 80}
    }
  ]
}
```

Fixture thực tế phải thêm ít nhất một compute `DOWN`, một compute `disabled` và một VM trên host khác để test negative filtering.

### 8.4 Service contract Checkpoint 1

`NetBoxService`:

- `load_snapshot()` — đọc/validate JSON một lần trong FastAPI lifespan/startup, fail fast nếu schema hoặc resource invariant sai.
- `get_compute(name)` — trả compute hoặc domain error `RESOURCE_NOT_FOUND`.
- `list_vms_by_compute(name)` — lọc VM có `compute` trùng chính xác và sắp xếp tăng dần theo tên.
- `list_available_computes(exclude_name)` — validate từng resource dimension, chỉ trả `UP + enabled + remaining > 0` cho cả VCPU/RAM/disk, rồi sắp xếp tên.

`IncidentService`:

- `create_recovery_context(type, resource)` — validate type, điều phối các query và dựng typed response.
- Không đọc file trực tiếp; chỉ phụ thuộc interface của topology provider.
- Không mutate fixture và không giữ global mutable state.

### 8.5 Error contract

| Trường hợp                        |      HTTP | Code                                                         |
| ------------------------------------ | --------: | ------------------------------------------------------------ |
| Payload sai/thiếu field             |       422 | `VALIDATION_ERROR`                                         |
| Incident type chưa hỗ trợ         |       422 | `UNSUPPORTED_INCIDENT_TYPE`                                |
| Compute không tồn tại             |       404 | `RESOURCE_NOT_FOUND`                                       |
| Fixture/schema lỗi khi khởi động | fail fast | `INVALID_TOPOLOGY_SNAPSHOT`                                |
| Lỗi nội bộ không dự kiến       |       500 | `INTERNAL_ERROR` + correlation id, không lộ stack/secret |

## 9. Data contract mục tiêu sau Checkpoint 1

### 9.1 Core models

| Model                | Field chính                                                                     |
| -------------------- | -------------------------------------------------------------------------------- |
| `Incident`         | id, external_event_id, type, resource, severity, detected_at, reported_by, state |
| `ResourceSnapshot` | schema_version, snapshot_at, source versions, computes, VMs, network, storage    |
| `RecoveryContext`  | incident, affected VMs/services, source failure domain, candidates, warnings     |
| `ServiceImpact`    | application, component, healthy/min replicas, priority, status, missing mappings |
| `RecoveryPlan`     | id, context_id, version, hash, objectives, actions, unplaced, risk, status       |
| `PlanAction`       | VM, action, target, order, dependency, reason, fallback, expected checks         |
| `ApprovalRecord`   | plan id/version/hash, decision, operator, timestamp, comment                     |
| `ExecutionResult`  | execution id, idempotency key, action/request ids, attempts, state, errors       |
| `CheckResult`      | check name/layer/mandatory, expected, actual, result, evidence, checked_at       |
| `AuditEvent`       | actor, timestamp, entity, old/new state, request/result summary                  |

Mọi snapshot và plan phải có `schema_version`, `observed_at/created_at` và source identifiers. Giá trị `unknown` không được tự động coi là `PASS`.

Persistence từ tuần 3 được chốt là SQLite + SQLAlchemy 2 + Alembic cho Software MVP; PostgreSQL là deployment extension. Transaction boundary phải bao quanh state transition + audit event tương ứng. Database có unique constraint cho `external_event_id`, `(plan_id, version)`, `plan_hash` theo version và `idempotency_key`; restart app phải load các execution/action chưa terminal rồi reconcile trước khi cho phép dispatch mới.

### 9.2 API roadmap

| Phase | Endpoint                                       | Mục đích                                                                                |
| ----- | ---------------------------------------------- | ------------------------------------------------------------------------------------------ |
| P1    | `POST /incidents`                            | Contract v1 không persistence: trả trực tiếp Recovery Context đúng ví dụ ban đầu |
| P2    | `POST /api/v2/incidents`                     | Lifecycle API: tạo persistent incident, trả`201` + `incident_id` + context envelope  |
| P2    | `GET /api/v2/incidents/{id}`                 | Xem incident, impact và timeline                                                          |
| P2    | `GET /api/v2/topology/computes`              | Read-only debug/UI view; filter status/AZ/rack                                             |
| P2    | `GET /api/v2/topology/computes/{name}/vms`   | Xem VM placement trên compute                                                             |
| P2    | `GET /api/v2/topology/vms/{id}/dependencies` | Xem app/network/storage mapping đã thu thập                                             |
| P3    | `POST /api/v2/incidents/{id}/plans`          | Sinh plan deterministic                                                                    |
| P3    | `GET /api/v2/plans/{id}`                     | Xem action, reason, rejected candidates, risk                                              |
| P4    | `POST /api/v2/plans/{id}/precheck`           | Chạy blocking/non-blocking checks                                                         |
| P4    | `POST /api/v2/plans/{id}/approve`            | Duyệt đúng version/hash                                                                 |
| P4    | `POST /api/v2/plans/{id}/reject`             | Từ chối và lưu comment                                                                 |
| P5    | `POST /api/v2/plans/{id}/execute`            | Trả`202` + execution id; dry-run mặc định                                            |
| P5    | `GET /api/v2/executions/{id}`                | Theo dõi action/retry/error                                                               |
| P5    | `GET /api/v2/executions/{id}/checks`         | Xem verification evidence                                                                  |

Versioning rule: contract P1 `POST /incidents` được giữ nguyên trong toàn kỳ demo, không âm thầm thêm envelope/id. Lifecycle là `/api/v2`; client mới dùng v2. Với v2, `external_event_id` mới trả `201 Created`, còn gửi lại cùng id trả `200 OK` và resource hiện có cùng header `Location`, không tạo incident trùng.

Error codes mở rộng: `CONTEXT_INCOMPLETE`, `NO_FEASIBLE_PLAN`, `PRECHECK_FAILED`, `PLAN_STALE`, `INVALID_STATE`, `EXECUTION_LOCKED`.

## 10. Application-aware Impact Analysis

### 10.1 Model tối thiểu

```text
Application
└── Service (priority, desired_replicas, min_healthy)
    └── Component (role/type, recovery_order)
        └── VM (current host, resources, constraints, health)
```

Ví dụ:

| Application      | Service | Component | VM        | Priority | Desired | Min healthy |
| ---------------- | ------- | --------- | --------- | -------- | ------: | ----------: |
| Digital Commerce | Payment | Database  | vm-db-01  | P0       |       1 |           1 |
| Digital Commerce | Payment | API       | vm-api-01 | P0       |       2 |           2 |
| Digital Commerce | Payment | API       | vm-api-02 | P0       |       2 |           2 |
| Digital Commerce | Payment | Web       | vm-web-01 | P1       |       1 |           1 |

Service state:

- `HEALTHY`: mọi component mandatory đạt `desired_replicas` và không có blocking warning.
- `DEGRADED`: mọi component vẫn đạt `min_healthy` nhưng chưa đạt `desired_replicas`, hoặc có warning policy.
- `DOWN`: ít nhất một mandatory component dưới `min_healthy`.
- `UNKNOWN`: thiếu mapping/health evidence; không được ngầm coi là healthy.

> **Lý thuyết ngắn — minimum viable service:** Một application có thể cần số replica tối thiểu khác nhau ở từng component. Planner nên phục hồi tập VM nhỏ nhất làm các component bắt buộc đạt `min_healthy`, thay vì máy móc cứu mọi VM theo thứ tự tên hoặc kích thước.

Giới hạn bắt buộc phải ghi trong báo cáo: `min_healthy` chỉ mô tả được replica đồng vai trò/độc lập. Nó không chứng minh DB leader/quorum, replication lag hay consistency. MVP nên demo service stateless hoặc replica-equivalent; workload stateful chỉ được real execute khi bổ sung `role`, `quorum`, `replication_health`, `data_health` và checklist tương ứng, nếu không phải `MANUAL_REQUIRED`.

MVP không triển khai dependency DAG tùy ý. `recovery_order` là số nguyên versioned trong policy; DAG, cycle validation và orchestration leader/follower là backlog.

### 10.2 Native HA gate

```text
Incident nhận được
      ↓
Observe native HA theo policy và lưu evidence
      ↓
Build/refresh Recovery Context + Application Impact
      ↓
Đánh giá service health sau observation window
      ↓
Service healthy? ── YES → NO_ACTION + lưu evidence
      │
      NO
      ↓
Recovery Planning
```

Phải cấu hình rõ `ha_observation_window`, nguồn health và điều kiện `NO_ACTION`. Không giả định Masakari luôn bật hoặc luôn thành công; trong demo mock, ghi rõ `native_ha_result = FAILED|DISABLED`.

### 10.3 Failure classification và disposition

Checkpoint 1 nhận trực tiếp `COMPUTE_DOWN`; từ tuần 3 phải xác nhận incident bằng evidence thay vì hành động chỉ dựa trên một alert. `COMPUTE_FAILURE` dưới đây là failure class nội bộ của chính incident `COMPUTE_DOWN`, không phải incident type thứ hai. `VM_FAILURE`, `APPLICATION_FAILURE` và `INFRA_DEPENDENCY_FAILURE` chỉ là taxonomy/future disposition, nằm ngoài scenario được thực thi trong MVP đầu.

| Failure class | Evidence tối thiểu | Disposition |
| --- | --- | --- |
| `UNCONFIRMED_ALERT` | Alert có nhưng Nova service/host và corroborating signal chưa xác nhận | Chờ/retry/escalate; không plan write action |
| `COMPUTE_FAILURE` | Source compute down/forced-down theo policy, nhiều VM cùng host bị ảnh hưởng hoặc host probe fail | Build batch context; fence; Nova `EVACUATE` nếu storage/policy cho phép |
| `VM_FAILURE` | Compute `UP/enabled`, VM `ERROR/SHUTOFF` hoặc VM probe fail | Future/out of scope; action ladder riêng theo policy/approval |
| `APPLICATION_FAILURE` | VM/network/storage healthy nhưng application check fail | Future/out of scope; application runbook hoặc `MANUAL_REQUIRED` |
| `INFRA_DEPENDENCY_FAILURE` | Cinder/storage hoặc Neutron/network prerequisite fail | Future taxonomy; blocking pre-check và escalation, không tự mutate dependency trong MVP |

Classifier output luôn có `class`, `confidence/evidence`, `observed_at` và `recommended_disposition`. Nếu evidence mâu thuẫn hoặc thiếu ở field critical, state là `CONTEXT_INCOMPLETE/MANUAL_REQUIRED`, không tự hạ cấp thành warning.

Host còn sống nhưng cần bảo trì/drain là class/workflow khác: disable scheduling rồi live/cold migrate theo policy. Host đã được khắc phục dùng health-check + re-enable workflow. Cả hai nằm trong backlog, không dùng chung runbook dead-host evacuation.

## 11. Recovery Planning

### 11.1 Hard constraints và soft preferences

> **Lý thuyết ngắn — hard/soft constraints:** Hard constraint bắt buộc phải thỏa, ví dụ target đang `UP/enabled`, đủ RAM và truy cập được storage. Soft preference chỉ xếp hạng các phương án đã hợp lệ, ví dụ ưu tiên cùng AZ, khác rack, ít fragmentation hoặc cân bằng tải tốt hơn.

Hard constraints dự kiến:

- Không chọn source compute hoặc compute `DOWN/disabled/maintenance`.
- Không chọn failure domain đã xác nhận lỗi.
- Đủ VCPU/RAM/DISK sau khi trừ reservation/headroom.
- Root disk/storage backend tương thích và reachable.
- Network/physnet/AZ/aggregate/trait tương thích.
- Nova server-group host anti-affinity không bị vi phạm; rack diversity/exclusion được kiểm tra riêng bằng topology NetBox/orchestrator.
- Fencing và data-loss policy đáp ứng action định dùng.

Soft preferences dự kiến:

- Khôi phục service P0/P1 và component thiếu replica trước.
- Cùng AZ nếu network/storage policy yêu cầu; khác rack để giảm correlated risk.
- Giảm số move và tổng resource movement.
- Hạn chế làm lệch tải hoặc tạo fragmentation.
- Ưu tiên target có headroom và health ổn định hơn.

> **Lý thuyết ngắn — anti-affinity:** Nova server-group anti-affinity ngăn replica nằm chung compute host. Rack diversity là custom orchestrator constraint dựa trên topology/failure domain, không nên gọi nhầm là khả năng rack-aware native của Nova.

### 11.2 Objective service-aware

MVP dùng objective **lexicographic** thay vì các hệ số `λ` mơ hồ. `recovery_policy.yaml` version `1.0` phải chốt các default sau và engine không được hard-code chúng:

```yaml
policy_version: "1.0"
priority_weight: {P0: 1000, P1: 100, P2: 10, P3: 1}
headroom_percent: {vcpu: 10, ram_mb: 10, disk_gb: 10}
objective_order:
  - maximize_fully_restored_service_value
  - maximize_restored_mandatory_replica_deficit
  - minimize_risk_tier
  - minimize_action_count
  - minimize_max_target_utilization
tie_break: [service_name, component_recovery_order, vm_name, compute_name]
```

`Service Recovery Value` là **metric riêng do đề tài định nghĩa**, không phải chuẩn ngành: một service chỉ nhận `priority_weight` khi mọi mandatory component đạt `min_healthy`; nếu chưa đạt thì giá trị full-service bằng 0, còn số mandatory replica đã phục hồi chỉ được tính ở objective thứ hai. Policy/weight phải version hóa và xuất hiện trong plan evidence.

Ràng buộc khái niệm:

```text
Mỗi VM được gán tối đa một target.
Tổng tài nguyên VM trên target không vượt capacity sau headroom.
Chỉ target thỏa network/storage/failure-domain/anti-affinity mới hợp lệ.
Service chỉ được tính recovered khi mọi mandatory component đạt min_healthy.
```

Với resource dimension `r`:

```text
effective_capacity_r = floor(total_r × (1 - headroom_percent_r / 100)) - reserved_r
remaining_r = effective_capacity_r - allocated_r - planned_r
feasible khi remaining_r >= vm_request_r cho mọi r
```

MVP không dùng overcommit (`allocation_ratio = 1.0`) trừ khi policy được thay đổi có chủ đích và được ghi trong benchmark.

> **Lý thuyết ngắn — service-aware planning:** Giá trị của plan được đo bằng service/component được phục hồi, không chỉ số VM. Cứu một DB và một API để Payment hoạt động có thể có giá trị hơn cứu nhiều VM logging nhưng Payment vẫn down.

### 11.3 Batch placement

> **Lý thuyết ngắn — batch placement:** Đây gần với generalized assignment/multi-dimensional bin-packing: nhiều VM phải gán vào nhiều compute dưới đồng thời VCPU/RAM/disk và policy. Chọn từng VM độc lập có thể tiêu hết candidate tốt và khiến workload critical phía sau không còn host phù hợp.

Greedy deterministic cho MVP:

1. Tính service deficits và tập VM tối thiểu có thể lấp deficit.
2. Sắp service theo `P0 → P1 → P2 → P3`, rồi `rto_target`, rồi tên.
3. Trong mỗi service, sắp VM theo số candidate khả thi tăng dần, normalized resource demand giảm dần, rồi tên; đây là định nghĩa `constraint_tightness` của MVP.
4. Lấy candidates từ provider, lọc toàn bộ hard constraints.
5. Xếp host theo objective/policy đã version hóa và tie-break cuối bằng compute name.
6. Gán VM, cập nhật remaining capacity trong snapshot plan.
7. Nếu không gán được, ghi `unplaced` + constraint/deficit cụ thể.
8. Chạy validator độc lập để khẳng định không vi phạm hard constraint.

> **Lý thuyết ngắn — greedy và MILP/CP-SAT:** Greedy nhanh, dễ giải thích nhưng không bảo đảm tối ưu toàn cục. MILP/CP-SAT mô hình objective/constraint chính xác hơn cho dataset vừa/nhỏ nhưng phức tạp và có thể tốn thời gian; dùng greedy làm MVP, solver làm baseline/extension để đo optimality gap.

### 11.4 Vai trò của Nova Placement/Scheduler

Planner đọc Placement allocation candidates để biết host/resource provider nào khả thi và bổ sung topology/application objective để xếp batch. Trong MVP thật, không tự `PUT /allocations`; Nova Scheduler vẫn xác minh/claim cuối khi evacuate. Nếu chỉ định target, phải dùng microversion tương thích và để scheduler validate; không dùng cơ chế `force` đã bị loại ở microversion mới. Xem [Placement API](https://docs.openstack.org/api-ref/placement/) và [Nova evacuate API](https://docs.openstack.org/api-ref/compute/#evacuate-server-evacuate-action).

### 11.5 Trường hợp thiếu capacity 10/10

Core MVP:

- Không overcommit ngoài policy.
- Không tự stop workload đang khỏe.
- Sinh partial plan theo service priority.
- Trả `unplaced`, resource deficit và manual options.

Extension `preemption` chỉ được mở khi có allowlist workload, impact analysis riêng và approval cấp cao hơn.

> **Lý thuyết ngắn — preemption:** Preemption dừng hoặc di chuyển workload ít quan trọng để giải phóng tài nguyên cho service critical. Đây là action tạo thêm blast radius, nên MVP chỉ phân tích/đề xuất chứ không tự thực hiện.

## 12. Pre-check, Approval và State Machine

### 12.1 State machine mục tiêu

Không dùng một enum chung cho mọi entity. Incident, Plan, Execution và từng Action có lifecycle riêng nhưng liên kết bằng foreign key/audit event. ADR-0001 là nguồn chuẩn của các enum và semantics dưới đây.

**Incident lifecycle:**

```text
RECEIVED → CONFIRMING → ANALYZING
                         ├── critical evidence missing
                         │      → CONTEXT_INCOMPLETE → MANUAL_REQUIRED
                         └── CONTEXT_READY
                                ├── native HA restored service → NO_ACTION
                                └── approved execution created
                                       → RECOVERY_IN_PROGRESS → VERIFYING
                                                                  ├── SUCCESS
                                                                  ├── PARTIAL
                                                                  ├── FAILED
                                                                  └── MANUAL_REQUIRED
```

Incident terminal states là `NO_ACTION`, `SUCCESS`, `PARTIAL`, `FAILED` và `MANUAL_REQUIRED`.

**Plan lifecycle:**

```text
DRAFT → VALIDATING
          ├── no accepted action → NO_FEASIBLE_PLAN
          ├── safe subset only   → PARTIAL_PLAN
          └── full objective     → PLANNED

PARTIAL_PLAN / PLANNED → PRECHECKING
                           ├── fail → PRECHECK_FAILED
                           └── pass → WAITING_APPROVAL → APPROVED / REJECTED

APPROVED → CONSUMED_BY_EXECUTION
         └── context drift trước dispatch → STALE
```

`REPLAN` không phải persisted state. Replan là command/process tạo context và plan version mới; approval cũ không được tái sử dụng. `PARTIAL_PLAN` chỉ được submit approval khi có ít nhất một action an toàn và policy cho phép partial recovery; UI phải hiển thị unmet objectives. `NO_FEASIBLE_PLAN` không tạo execution.

**Execution lifecycle:**

```text
PENDING → REVALIDATING
             ├── drift → BLOCKED_STALE
             └── pass → RUNNING → VERIFYING
                                      ├── SUCCESS
                                      ├── PARTIAL
                                      ├── FAILED
                                      └── MANUAL_REQUIRED
```

**Per-action lifecycle:**

```text
PENDING → DISPATCHING → ACCEPTED → POLLING → SUCCEEDED / FAILED
              └── response bất định → UNKNOWN → RECONCILING
                                                   ├── ACCEPTED / POLLING
                                                   ├── SUCCEEDED / FAILED
                                                   └── MANUAL_REQUIRED
```

Cross-entity transition bắt buộc:

| Child outcome/event | Incident transition |
| --- | --- |
| M2 xác nhận service healthy sau native HA | `CONTEXT_READY → NO_ACTION` |
| Critical context missing | `ANALYZING → CONTEXT_INCOMPLETE → MANUAL_REQUIRED` |
| Plan `NO_FEASIBLE_PLAN` | `CONTEXT_READY → MANUAL_REQUIRED` |
| Plan `REJECTED` | `CONTEXT_READY → MANUAL_REQUIRED` với operator reason |
| `PRECHECK_FAILED` và policy còn cho replan | `CONTEXT_READY → ANALYZING`, rồi tạo context/plan version mới |
| `PRECHECK_FAILED` không còn safe replan | `CONTEXT_READY → MANUAL_REQUIRED` |
| Plan `STALE` hoặc Execution `BLOCKED_STALE` | `RECOVERY_IN_PROGRESS` hoặc `CONTEXT_READY → ANALYZING`; approval cũ mất hiệu lực |
| Execution được tạo từ plan approved | `CONTEXT_READY → RECOVERY_IN_PROGRESS` |
| Execution `VERIFYING` | `RECOVERY_IN_PROGRESS → VERIFYING` |
| Execution terminal | Incident nhận cùng `SUCCESS`, `PARTIAL`, `FAILED` hoặc `MANUAL_REQUIRED` |

> **Lý thuyết ngắn — state machine:** State machine quy định transition nào hợp lệ và bằng chứng nào cần có. Nó ngăn execute trước approve, approve plan cũ, hoặc đánh dấu thành công khi chưa verify.

Mỗi transition lưu entity, actor, timestamp, source state, target state, reason và evidence. `UNKNOWN` không được coi là terminal success; hệ thống reconcile, sau timeout thì chuyển `MANUAL_REQUIRED`. `BLOCKED_EXTERNAL` chỉ thuộc báo cáo lab readiness/acceptance, không phải runtime state của Incident, Plan, Execution hoặc Action. Transition bất hợp lệ trả `INVALID_STATE`, không tự “nhảy cóc”.

### 12.2 Pre-checks

Blocking checks trước approval/execute:

- Incident và source failure vẫn còn hiệu lực.
- Source host đã được fence cho action evacuate.
- Compute service disabled/down/forced_down phù hợp với policy.
- Target vẫn `UP/enabled`, capacity/headroom còn đủ.
- Placement traits/aggregate/AZ vẫn phù hợp.
- Storage reachable; root disk/data-loss risk đã được operator thấy.
- Network/port/physnet/security prerequisites đủ.
- Anti-affinity/failure-domain không vi phạm.
- Plan version/hash khớp context hiện tại.

Non-blocking checks tạo warning:

- Telemetry optional bị thiếu.
- Target load trend không lý tưởng nhưng vẫn trong ngưỡng.
- External firewall cần manual confirmation.

### 12.3 Fencing và split-brain

> **Lý thuyết ngắn — fencing/split-brain:** Fencing bảo đảm host/VM nguồn không thể tiếp tục chạy hoặc truy cập shared resources trước khi dựng bản mới; tùy lab có thể là hard power-off hoặc cơ chế cô lập network/storage đủ mạnh. Nếu VM cũ và mới cùng ghi shared disk, split-brain có thể gây corruption; `source_host_fenced` vì vậy là blocking check và không đồng nhất với `disable scheduling`.

Nova yêu cầu host nguồn thực sự down/fenced trước evacuation; disable compute service chỉ ngăn schedule mới. Evacuation dùng cơ chế rebuild ở host khác, nên ephemeral local disk có thể mất; context/plan phải có `root_disk_type`, `boot_from_volume`, `shared_storage` và `data_loss_risk`. Từ Nova microversion 2.95, server giữ Nova status `SHUTOFF` (stopped) sau evacuate và có thể cần action start riêng; đây là nội dung phải xác minh trong `lab_profile.json` trước khi code executor.

### 12.4 Human approval và plan version

> **Lý thuyết ngắn — human-in-the-loop:** Operator duyệt một phương án có target, action và risk cụ thể trước thao tác write. Approval phải gắn với `plan_id + version + hash`; plan đổi dù chỉ một destination thì approval cũ hết hiệu lực.

Approval record tối thiểu:

- operator id/name/role;
- plan id/version/hash;
- approve/reject;
- timestamp và comment;
- pre-check summary;
- acknowledged warnings/data-loss risk.

### 12.5 Staleness và revalidation

> **Lý thuyết ngắn — TOCTOU/plan staleness:** Capacity, VM state hoặc host health có thể đổi giữa lúc lập plan và lúc execute. Executor phải chụp snapshot mới; nếu thay đổi ảnh hưởng feasibility thì đánh dấu `STALE`, tạo context/plan version mới và yêu cầu approve lại.

## 13. Executor an toàn

### 13.1 Execution contract

- Dry-run là mặc định.
- Chỉ plan `APPROVED` đúng hash mới chạy.
- Lock theo incident và theo VM để ngăn race với request khác.
- Mỗi action có idempotency key ổn định.
- Adapter ghi request id/instance action id để poll và audit.
- Timeout/retry/backoff có giới hạn; không retry mù với action không idempotent.
- Action fallback khác plan ban đầu phải quay lại replan/approval.
- Trước dispatch phải persist action intent/fingerprint. Nếu process crash ở trạng thái `DISPATCHING/UNKNOWN`, restart sẽ query instance action/current state để reconcile và không tự dispatch lại khi kết quả còn bất định.
- Failure của prerequisite chặn toàn bộ dependent actions; independent actions chỉ tiếp tục khi `continue_independent_on_failure=true` trong policy. MVP không hứa rollback nguyên tử/compensation cho evacuation đã hoàn tất; failure giữa batch dẫn tới `PARTIAL|FAILED|MANUAL_REQUIRED` và replan.

> **Lý thuyết ngắn — dry-run:** Dry-run sinh action, target, thứ tự và checklist nhưng không thay đổi OpenStack. Nó giúp kiểm tra logic, demo sớm và cho operator review trước khi cấp quyền thực thi thật.

> **Lý thuyết ngắn — idempotency:** Alert hoặc request lặp không được tạo recovery trùng. Hệ thống dùng `external_event_id`, idempotency key và execution lock để trả kết quả cũ hoặc từ chối action đang chạy.

### 13.2 Recovery action ladder

Trong case `COMPUTE_DOWN`, primitive Nova để chuyển workload khỏi dead host là `EVACUATE`; standalone `REBUILD` không phải fallback để rehome VM từ host chết. Nếu local root/ephemeral data làm evacuation không an toàn, core phải `BLOCK/MANUAL_REQUIRED` hoặc dùng một workflow tạo replacement từ image/backup được thiết kế và duyệt riêng. **Không live migrate từ host đã chết.** Xem thêm [Nova: evacuate versus rebuild](https://docs.openstack.org/nova/latest/contributor/evacuate-vs-rebuild).

```text
COMPUTE_DOWN + fenced + storage compatible
    → disable scheduling
    → set forced_down nếu policy/microversion yêu cầu
    → EVACUATE
    → START nếu post-evacuate status là SHUTOFF
    → VERIFY

COMPUTE_DOWN + local ephemeral/root disk risk
    → BLOCK/MANUAL_REQUIRED
    → optional separate RESTORE_REPLACEMENT workflow từ image/backup

VM failure + compute UP
    → START/SOFT_REBOOT/HARD_REBOOT/REBUILD theo policy
```

External fencing evidence phải có **trước** `forced_down`; `forced_down` không phải fencing. VM failure là test phân loại/future scenario; không được làm scope chính trước khi Compute Down hoàn thành.

### 13.3 Generated runbook và network/firewall boundary

Software MVP bắt buộc sinh `execution_runbook.yaml` từ đúng plan version/hash. Runbook gồm ordered actions, preconditions, target, timeout/retry policy, expected verification, rollback/manual notes và các proposed network/firewall changes. Executor chỉ tự gọi các OpenStack action đã allowlist; external firewall mutation vẫn là manual/approved task có evidence.

Software MVP phải chuyển canonical YAML thành một Ansible Playbook deterministic, có `plan_id/version/hash`, ordered tasks, preconditions, variable placeholders và verification tasks; playbook không chứa secret và mặc định chỉ để review/`--check`, không auto-apply. Terraform không được dùng làm core executor vì incident recovery là workflow imperative/asynchronous và thay đổi Terraform state có thể tạo xung đột.

## 14. Verification và kết luận incident

### 14.1 Checklist nhiều lớp

| Layer       | Mandatory checks ví dụ                                                         |
| ----------- | -------------------------------------------------------------------------------- |
| Compute     | VM expected state, destination host, task state sạch, target compute up/enabled |
| Storage     | volume attachment đúng, shared storage reachable, marker/checksum nếu có     |
| Network     | port ACTIVE, binding host, fixed IP, SG, route/physnet prerequisite              |
| Application | TCP port, HTTP`/health`, service heartbeat, `min_healthy` replicas           |
| Audit       | action id, timestamps, expected/actual/evidence đầy đủ                       |

Aggregation rule:

| Điều kiện                                                                                                                               | Final result        |
| ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------- |
| Mọi recovery action và mandatory compute/storage/network/application check pass; service đạt objective                                 | `SUCCESS`         |
| Infra/action mandatory pass nhưng application chưa đạt`min_healthy`, hoặc partial plan chỉ phục hồi được một phần objective | `PARTIAL`         |
| Có action fail hoặc mandatory compute/storage/network check fail                                                                         | `FAILED`          |
| Critical evidence vẫn không xác định sau reconcile timeout                                                                            | `MANUAL_REQUIRED` |

API enum cuối được cố định là `SUCCESS | PARTIAL | FAILED | MANUAL_REQUIRED`. `UNKNOWN` chỉ là trạng thái tạm của check/action đang reconcile; `NO_ACTION` là terminal riêng ở incident khi native HA đã giữ service healthy.

### 14.2 RTO và RPO

> **Lý thuyết ngắn — RTO/RPO:** Recovery Time Objective là mục tiêu thời gian tối đa chấp nhận được để đưa service trở lại. Recovery Point Objective là lượng dữ liệu tối đa có thể mất tính theo thời gian; evacuation không tự bảo đảm RPO nếu không có replication/backup phù hợp. MVP đo actual recovery time và so với `rto_target`; marker/checksum chỉ là evidence integrity, không phải phép đo RPO.

Các mốc thời gian cần đo riêng:

- `detection_latency = confirmed_at - detected_at`;
- `analysis_time = context_ready_at - analyzing_at`;
- `planning_time = planned_at - context_ready_at`;
- `approval_wait_time = approved_at - waiting_approval_at`;
- `execution_time = execution_finished_at - executing_at`;
- `verification_time = final_at - verifying_at`;
- `observed_recovery_time = service_healthy_at - incident_detected_at`;
- `rto_met = observed_recovery_time <= rto_target`.

Không gộp approval wait với engine performance khi đánh giá thuật toán.

## 15. Roadmap cụ thể theo 7 tuần

### Tuần 1 — 24/08–30/08: Chốt bài toán và điều kiện đầu vào

**Trạng thái:** `COMPLETED` ngày `01/09/2026`. Decision record và evidence: [ADR-0001](./docs/decisions/0001-week-1-foundation.md).

Kết quả:

- [x] Chốt câu mô tả đề tài, in/out scope và hai mức vertical slice.
- [x] Lập reuse/build matrix cho Nova, Placement, Masakari, NetBox, OTel và dependency ngoại vi.
- [x] Audit workspace và dữ liệu synthetic bằng evidence từ file hiện có.
- [x] Chốt source-of-truth matrix, glossary và bốn lifecycle tách biệt.
- [x] Lập prerequisite register P01–P09 cho lab, fencing, storage, account và microversion.

**Gate W1: `PASS`.** Mục tiêu được mô tả là phục hồi workload/service; `COMPUTE_DOWN` là scenario duy nhất của MVP đầu; mọi external dependency có vai trò, owner và hành vi khi thiếu evidence. OpenStack Lab Readiness vẫn là `BLOCKED_EXTERNAL` vì P01–P09 đang `UNKNOWN`; điều này không làm Gate W1 thất bại.

### Tuần 2 — 31/08–06/09: Checkpoint 1 — `POST /incidents` → Recovery Context

**Trạng thái:** `COMPLETED` ngày `01/09/2026`. Backend, test suite và evidence: [Checkpoint `context-v1`](./docs/checkpoints/context-v1.md).

#### 01/09

- Tạo `dr-system/`, `pyproject.toml`, package folders và test skeleton.
- Khai báo runtime/dev dependencies tối thiểu: FastAPI, Uvicorn, Pydantic v2, pytest và httpx.
- Viết `data/netbox_mock.json` theo schema v1.
- Chốt request/response/error contract.

#### 02/09

- Viết Pydantic models cho Incident, SourceLocation và RecoveryContext.
- Viết loader/validator của `NetBoxService`.
- Test fixture malformed, duplicate names và missing foreign reference.

#### 03/09

- Viết `IncidentService` và `POST /incidents`.
- Trả đúng context cho `compute-01`.
- Bảo đảm sort deterministic và không mutate JSON.

#### 04/09

- Viết API/unit tests happy path và negative cases.
- Chuẩn hóa HTTP errors và logging correlation id.
- Thêm `/healthz` và OpenAPI docs mặc định.

#### 05/09

- Viết README: setup, run, test, curl và expected JSON.
- Chạy clean-environment smoke test.
- Review code boundaries và loại bỏ abstraction chưa dùng.

#### 06/09

- Demo checkpoint, lưu test evidence và gắn nhãn checkpoint nội bộ `context-v1` trong tài liệu/release note; chỉ tạo Git tag nếu workspace đã được khởi tạo Git.
- Chỉ chuyển tuần 3 nếu toàn bộ gate đạt.

**Gate W2: `PASS`.** Toàn bộ Definition of Done tại mục 16.1 đã đạt; 46 unit/API tests pass và Uvicorn/curl smoke test trả đúng Recovery Context deterministic.

### Tuần 3 — 07/09–13/09: Persistence + Application-aware Impact + Candidate Filter

- Thêm mock `Application → Service → Component → VM`, priority, `desired_replicas` và `min_healthy`.
- Cài SQLite + SQLAlchemy 2 + Alembic; tạo schema/repositories/transaction boundaries và unique constraints đã chốt.
- Thêm `/api/v2/incidents`, incident id, snapshot timestamps và lifecycle persistence; giữ v1 không đổi.
- Tính service `HEALTHY/DEGRADED/DOWN/UNKNOWN`.
- Cài failure classifier và native-HA gate sau Impact Analysis.
- Cài hard-constraint filter và rejected reasons.
- Test service state, mapping thiếu, target down/disabled, Nova host anti-affinity và rack-diversity constraints.

**Gate W3:** service impact giải thích được từ data; candidate filter không nhận host vi phạm; restart app vẫn giữ incident/context và unique event không bị nhân đôi.

### Tuần 4 — 14/09–20/09: Batch Planner + Pre-check + Approval

- Cài greedy deterministic batch placement đúng `recovery_policy.yaml` version 1.0.
- Sinh Recovery Plan gồm actions, unplaced, reason/risk, policy version và context reference.
- Test đủ/thiếu capacity, partial/no-feasible plan và deterministic hash.
- Cài state machine và transition guard.
- Version/hash cho context và plan.
- Checklist YAML schema, blocking/non-blocking severity.
- API precheck, approve, reject và dry-run.
- Revalidation/state-drift simulation.
- Fencing evidence model; tách `disabled` khỏi `fenced`.
- Audit event cho mọi transition.
- RBAC tối thiểu cho demo bằng viewer/operator tokens lấy từ environment: viewer chỉ đọc, operator mới approve/execute; production SSO/OIDC ngoài MVP.
- Basic per-identity rate limit cho approve/execute; distributed rate limiting là production extension.
- Test viewer không approve/execute và operator chỉ execute trong allowlisted demo environment.

**Gate W4:** execute chưa approve bị chặn; plan đổi làm approval cũ vô hiệu; fencing fail không thể đi tiếp; state drift tạo replan.

### Tuần 5 — 21/09–27/09: Mock Executor + Closed-loop Verification + UI tối thiểu

- Tạo adapter protocol và mock OpenStack executor.
- Execution lock, idempotency key, retry/backoff giới hạn.
- Persist per-action states/external ids; reconcile action dở dang khi restart; inject fault/timeout/crash-after-accept.
- Verification compute/storage/network/application bằng mock checks.
- Aggregation `SUCCESS/PARTIAL/FAILED/MANUAL_REQUIRED` theo bảng deterministic.
- Sinh `execution_runbook.yaml` từ approved plan, gồm ordered action, preconditions, expected checks, firewall/network proposal và manual confirmations; không tự mutate external firewall.
- Sinh Ansible Playbook review-only từ cùng canonical runbook; test mọi action/task giữ đúng order, target và plan hash, không chứa secret.
- War-Room UI bắt buộc nhưng nhỏ: FastAPI server-rendered HTML + HTMX/plain JS polling, một trang incident → context → plan → approve → execution → checks.
- SSE/WebSocket là stretch; Terraform không dùng cho core incident execution.

**Gate W5:** full mock flow chạy end-to-end qua API và UI; canonical YAML + Ansible Playbook review-only được sinh; duplicate/crash-restart không tạo action mù lần hai; VM ACTIVE nhưng app fail phải ra `PARTIAL`.

### Tuần 6 — 28/09–04/10: OpenStack lab integration, test và benchmark

Điều kiện vào tuần:

- Có allowlisted tenant/workload lab.
- Account/API/microversion đã ghi trong `lab_profile.json`.
- Shared storage/root disk behavior đã xác minh.
- Có fencing/power-off evidence và maintenance window.
- Có ít nhất một target đủ capacity cho happy case.

**Track A — Software MVP/benchmark bắt buộc:**

- Viết deterministic DR scenario generator/enricher theo contract (`VM→host`, capacity, AZ/rack, service graph); không giả định generator NetBox hiện có đã cung cấp các field này.
- Chạy FIFO, VM-priority và service-aware trên cùng seed/failure snapshot ở small/medium scale.
- Đo planning latency, recovered service value, unplaced, utilization và hard-constraint violations.
- Large-scale benchmark là stretch nếu scenario generator/runner hoàn thành sớm.

**Track B — OpenStack Lab Acceptance, chỉ chạy khi toàn bộ prerequisite đạt:**

- Read-only adapter: Nova servers/services/hypervisors, Placement candidates, Neutron ports, Cinder volumes.
- Đối chiếu runtime IDs với topology/application catalog.
- Chạy manual evacuation baseline tối thiểu 3 lần trên cùng workload/failure procedure; lưu actual recovery time và tách approval wait.
- Bật real executor bằng feature flag trong lab, dry-run vẫn là default.
- E2E Compute Down, safe-stop, state drift, timeout và partial capacity.
- Đo observed recovery time, downtime, RTO compliance, constraint violations và integrity evidence.

**Gate W6-A bắt buộc:** benchmark reproducible pass và Software MVP vẫn full mock E2E. **Gate W6-B riêng:** real E2E chỉ `PASS` khi evacuation + verification thật thành công; thiếu prerequisite được ghi `BLOCKED_EXTERNAL`, tuyệt đối không ghi là pass hoặc trình bày như real recovery.

### Tuần 7 — 05/10–11/10: Report, demo, freeze và bàn giao

- Freeze scope/code, không thêm Rack Down hoặc AI.
- Hoàn thiện architecture/sequence/state diagrams và API contract.
- Viết deployment/user guide, sample config không chứa secret.
- Tổng hợp test report, benchmark, limitations và threat/safety notes.
- Viết demo script 10–15 phút, rehearsal tối thiểu 3 lần.
- Quay video E2E dự phòng.
- Đóng gói source, fixtures, policies, checks và backlog.

**Gate W7:** người khác có thể setup, chạy test và replay Software MVP theo README; báo cáo phân biệt rõ mock/real, ghi kết quả W6-B là `PASS|FAILED|BLOCKED_EXTERNAL`, và tách phần tự phát triển/dependency.

## 16. Definition of Done theo milestone

### 16.1 DoD Checkpoint 1

- [x] `dr-system` chạy bằng một lệnh được ghi trong README.
- [x] `POST /incidents` nhận đúng `COMPUTE_DOWN/compute-01`.
- [x] Response có đúng rack/AZ, đúng tập affected VMs và chỉ compute hợp lệ.
- [x] Kết quả deterministic giữa các lần chạy.
- [x] Unknown compute trả 404; type sai/payload sai trả 422.
- [x] Source/down/disabled compute không xuất hiện trong candidate pool.
- [x] Fixture schema hoặc reference sai làm app fail fast với lỗi dễ hiểu.
- [x] Service không mutate dữ liệu mock.
- [x] Unit/API tests pass; README có curl và expected output.
- [x] Chưa có bất kỳ write call nào ra OpenStack.

### 16.2 DoD Impact + Planner

- [ ] Mỗi affected VM truy ngược được compute/rack/AZ và Application/Service/Component hoặc được đánh dấu mapping thiếu.
- [ ] Service state tính đúng theo `desired_replicas/min_healthy`; mất redundancy nhưng còn min phải là `DEGRADED`.
- [ ] Planner thỏa toàn bộ hard constraints và validator độc lập xác nhận.
- [ ] Plan có accepted/rejected candidate reasons, risk, unplaced và deficits.
- [ ] Cùng context/policy tạo cùng plan/hash.
- [ ] Thiếu capacity trả partial/`NO_FEASIBLE_PLAN`, không bịa target và không overcommit.
- [ ] SQLite migration chạy được; restart app không mất incident/plan và duplicate `external_event_id` không tạo row mới.

### 16.3 DoD Approval + Execute

- [ ] Planner không có write credential.
- [ ] Plan chưa approve hoặc sai hash không thể execute.
- [ ] Plan stale bắt buộc replan/approve lại.
- [ ] Fencing là blocking gate cho evacuation.
- [ ] Idempotency/lock ngăn double execution.
- [ ] Dry-run là default và hiển thị đúng action/order/target.
- [ ] Retry có giới hạn; mọi request/action/error có audit id.
- [ ] Per-action intent/state/external id được persist; action `UNKNOWN` được reconcile trước khi cho phép re-dispatch.
- [ ] Crash sau external API accepted không dẫn đến tự động gửi action lần hai khi chưa xác minh.
- [ ] Viewer không approve/execute; operator chỉ execute trong allowlisted environment.

### 16.4 DoD Verification + Demo

- [ ] Không coi HTTP 202 hoặc VM ACTIVE là success cuối.
- [ ] Compute, storage, network và application mandatory checks có expected/actual/evidence.
- [ ] Infra pass nhưng app fail được kết luận `PARTIAL`.
- [ ] Demo đi đủ Input → Context → Plan → Approve → Execute → Verify.
- [ ] Có `execution_runbook.yaml` đúng plan version/hash; firewall change chỉ là proposal/manual confirmation.
- [ ] Có Ansible Playbook deterministic sinh từ canonical runbook, không chứa secret và không auto-apply.
- [ ] UI một trang hiển thị đủ context/plan/precheck/approval/execution/checks bằng polling.
- [ ] Software MVP lưu đủ timestamp, tính `observed_mock_recovery_time` và test đúng logic `rto_met` bằng synthetic policy target; đây không phải cam kết RTO vận hành.
- [ ] Có mock downtime/planning time và không có hard-constraint violation.
- [ ] Có report, README, API/diagram, test evidence, video fallback và limitations.

### 16.5 OpenStack Lab Acceptance — tách khỏi Software MVP

- [ ] P01–P09 có evidence và `lab_profile.json` hoàn chỉnh.
- [ ] Manual evacuation baseline chạy được trước automation.
- [ ] Operational `rto_target` được chốt sau manual baseline và có owner/approval; chỉ Track B mới báo operational RTO compliance.
- [ ] Real adapter đọc đúng Nova/Placement/Neutron/Cinder và join đúng identity.
- [ ] Real execute chỉ bật bằng feature flag/allowlist và có fencing evidence.
- [ ] Compute Down thật/lab đi qua evacuate, optional start khi `SHUTOFF`, rồi verification.
- [ ] Kết quả được ghi đúng `PASS`, `FAILED` hoặc `BLOCKED_EXTERNAL`; chỉ `PASS` mới được tuyên bố real E2E thành công.

## 17. Test plan

### 17.1 Test bắt buộc ngay Checkpoint 1

| ID      | Scenario                             | Expected                                                                                              |
| ------- | ------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| CTX-001 | `compute-01 DOWN`                  | Đúng rack/AZ; VM`[vm-api-01, vm-web-01]`; compute `[compute-05, compute-06]` theo thứ tự tên |
| CTX-002 | Compute không tồn tại             | 404`RESOURCE_NOT_FOUND`                                                                             |
| CTX-003 | Type`RACK_DOWN` ở version 1       | 422`UNSUPPORTED_INCIDENT_TYPE`                                                                      |
| CTX-004 | Payload thiếu`resource`           | 422 validation error                                                                                  |
| CTX-005 | Candidate là source                 | Bị loại                                                                                             |
| CTX-006 | Candidate DOWN/disabled              | Bị loại và output ổn định                                                                       |
| CTX-007 | Fixture thiếu VM→compute reference | App fail fast, chỉ ra reference lỗi                                                                 |
| CTX-008 | Gọi lặp cùng payload              | Cùng context; không mutate fixture                                                                  |

### 17.2 Test planner/impact

| ID      | Scenario                                                                      | Expected                                                                       |
| ------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| IMP-001 | Healthy replicas dưới`desired_replicas` nhưng vẫn đạt `min_healthy` | `DEGRADED`; chưa coi `HEALTHY`                                            |
| IMP-002 | Mandatory component dưới`min_healthy`                                     | Service`DOWN`, deficit rõ                                                   |
| PLN-001 | Đủ capacity                                                                 | Tất cả required VM được đặt hợp lệ                                    |
| PLN-002 | Thiếu capacity                                                               | Critical service được ưu tiên; unplaced có reason                        |
| PLN-003 | Nova host anti-affinity hoặc custom rack-diversity block                     | Candidate bị loại theo đúng constraint, không trộn semantics             |
| PLN-004 | Network/storage incompatible                                                  | Candidate bị loại theo đúng constraint                                     |
| PLN-005 | Native HA thành công                                                        | `NO_ACTION`, không sinh plan thực thi                                      |
| PLN-006 | Mapping critical application/service thiếu                                   | Incident`CONTEXT_INCOMPLETE → MANUAL_REQUIRED`; không sinh executable plan |

### 17.3 Test governance/execution/verification

| ID      | Scenario                                                        | Expected                                                                                                     |
| ------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| GOV-001 | Approve v1 rồi đổi target thành v2                          | Approval v1 vô hiệu                                                                                        |
| GOV-002 | Execute chưa approve                                           | Reject; không có write action                                                                              |
| GOV-003 | Source chưa fence                                              | Blocking fail                                                                                                |
| GOV-004 | Capacity đổi sau approve                                      | `STALE`; command replan tạo context/plan version mới                                                     |
| EXE-001 | Bấm execute hai lần                                           | Một action duy nhất                                                                                        |
| EXE-002 | Nova timeout/503                                                | Retry/backoff giới hạn, audit rõ                                                                          |
| EXE-003 | Backend crash sau API accepted nhưng trước khi lưu response | Action`UNKNOWN/RECONCILING`; query external state trước, không tự dispatch lại                        |
| EXE-004 | Action thứ hai trong batch fail                                | Dependent actions bị block; independent action chỉ tiếp tục nếu policy cho phép; result không success |
| VER-001 | VM ACTIVE + app healthy                                         | `SUCCESS`                                                                                                  |
| VER-002 | VM ACTIVE + HTTP health fail                                    | `PARTIAL`                                                                                                  |
| VER-003 | Storage/network mandatory fail                                  | `FAILED`                                                                                                   |
| SEC-001 | Viewer gọi approve/execute                                     | 403; không state change/action                                                                              |
| SEC-002 | Operator execute ngoài allowlist                               | 403/block; audit reason                                                                                      |
| SEC-003 | Vượt write-endpoint rate limit                                | 429; không tạo transition/action                                                                           |
| RUN-001 | Export approved plan sang Ansible                               | Đúng plan hash/order/target/checks; không có secret; không auto-apply                                   |
| E2E-001 | Compute Down happy path                                         | Full timeline + observed recovery time; mock chỉ test synthetic`rto_met`, lab báo operational RTO riêng |
| E2E-002 | Safe stop/partial                                               | Không execute unsafe; lý do/manual action rõ                                                              |

### 17.4 Chất lượng test

- Core domain services/planner/check engine: target coverage tối thiểu 80%; ưu tiên branch critical hơn chạy theo số đẹp.
- Contract tests cho adapters để mock và real provider có cùng semantics.
- Fixture có seed/version để benchmark tái lập.
- Property/invariant tests cho `capacity never negative`, `no source target`, `no hard constraint violation`.
- E2E test không dùng production credential/resource.

## 18. Evaluation và tiêu chí nghiên cứu

### 18.1 Baselines

So sánh ít nhất ba cách:

1. FIFO theo VM.
2. VM-priority greedy.
3. Service-aware batch planner của đề tài.

Optional: MILP/CP-SAT optimal solution trên dataset nhỏ để đo khoảng cách tối ưu.

Mỗi thuật toán nhận cùng immutable snapshot, policy version, seed và time limit; chạy ít nhất 10 lần để báo median/p95 planning latency, còn solution quality phải giống nhau giữa các lần vì engine deterministic. Manual operational baseline chỉ thực hiện ở Track B trên cùng workload/failure procedure tối thiểu 3 lần và được báo riêng, không trộn approval wait vào planner latency.

### 18.2 Metrics

- Tỷ lệ critical services được đưa về `min_healthy`.
- Tổng policy-defined Service Recovery Value và policy version.
- Số VM recovered và số VM unplaced.
- Hard-constraint violations — mục tiêu bắt buộc bằng 0.
- Planning latency theo số VM/candidate.
- Số move/action và mức load imbalance sau plan.
- Software MVP: observed mock recovery/execution/verification time và logic `rto_met` với synthetic target.
- OpenStack Lab Acceptance: observed operational recovery time, approved `rto_target/rto_met`, execution time và verification time.
- Success/partial/failure rate.
- Số bước operator và thời gian approval tách riêng.
- Data marker/checksum integrity khi lab hỗ trợ.

### 18.3 Experiment matrix

| Dataset                   | Capacity            | Constraint               | Mục đích                                                                |
| ------------------------- | ------------------- | ------------------------ | -------------------------------------------------------------------------- |
| Small deterministic       | Dư                 | Cơ bản                 | Correctness và explainability                                             |
| Small deterministic       | Thiếu              | Priority/min_healthy     | Chứng minh service-aware objective                                        |
| Medium synthetic          | 70–90% load        | Anti-affinity/rack       | Planning latency/quality                                                   |
| Large synthetic (stretch) | Cao                 | Mixed constraints        | Stress test collector/planner sau khi scenario generator pass medium scale |
| OpenStack lab             | Đủ cho happy case | Real Nova/Cinder/Neutron | E2E, observed recovery time và RTO compliance                             |

Không đặt target RTO tuyệt đối trước khi có manual baseline và đặc điểm lab. Báo cáo phải so với baseline cùng môi trường, cùng workload và cùng failure injection.

## 19. Điều kiện tiên quyết

Tại thời điểm đóng W1, P01–P09 đều là `UNKNOWN`; OpenStack Lab Readiness vì vậy là `BLOCKED_EXTERNAL`. Bảng chi tiết và microversion rules nằm trong [ADR-0001](./docs/decisions/0001-week-1-foundation.md#8-openstack-lab-prerequisite-register).

| ID | Điều kiện | Status | Owner vai trò | Evidence bắt buộc | Hạn chốt | Nếu thiếu |
| --- | --- | --- | --- | --- | --- | --- |
| P01 | Account/policy đọc all-project và write trên allowlisted lab | `UNKNOWN` | OpenStack IAM/admin | Project/role, policy probe và resource allowlist | Trước real adapter/write | Chỉ mock/read-only; real executor disabled |
| P02 | Endpoint, region, release, Nova/Placement microversion và SDK compatibility | `UNKNOWN` | OpenStack platform admin | Sanitized discovery output và compatibility record | Trước real adapter | Không pin client; real executor disabled |
| P03 | Root/local/shared/boot-from-volume behavior | `UNKNOWN` | Storage admin | Per-workload assessment và manual test evidence | Trước evacuation | `MANUAL_REQUIRED`; action bị block |
| P04 | Fencing/power-off hoặc approved isolation provider | `UNKNOWN` | Infrastructure operator | Provider, target, actor, result và fresh timestamp | Trước W6 E2E | Không evacuate; không override |
| P05 | Target capacity/headroom, traits, AZ và scheduler acceptance | `UNKNOWN` | Capacity/compute admin | Placement snapshot/generation và Nova validation | Trước W6 | Chỉ partial/safe-stop hoặc block |
| P06 | NetBox↔Nova join và application/service/priority mapping | `UNKNOWN` | DCIM + service owner | Join contract, mapping version, owner và completeness report | Trước W3 gate | Context incomplete; planner blocked |
| P07 | Network/physnet/SG/firewall và storage reachability | `UNKNOWN` | Network + storage admin | Binding/path test và dependency confirmation | Trước W4/W6 | Blocking pre-check/manual task |
| P08 | Maintenance window, supervisor, kill switch và rollback | `UNKNOWN` | Change manager + DR operator | Approved change và rollback rehearsal | Trước failure injection | Không tác động host thật |
| P09 | Demo workload, health contract, marker/checksum và RTO baseline | `UNKNOWN` | Service owner/SRE | Manifest, health/min-replica contract và baseline | Trước W5/W6 | Không claim service recovery/RTO/integrity |

Rule P02 đã khóa: target host chỉ định cần Nova `>=2.29`; executor không gửi `force` và Nova `>=2.68` không chấp nhận field này; Nova `>=2.95` giữ VM ở trạng thái dừng sau evacuation nên plan cần `START` khi policy yêu cầu; Placement allocation candidates cần API `>=1.10`. Mọi giá trị vẫn phải được discover và xác minh trên lab, không điền giả định.

## 20. Risk register

| ID  | Rủi ro                                              |     Mức | Giảm thiểu                                                           |
| --- | ---------------------------------------------------- | -------: | ---------------------------------------------------------------------- |
| R01 | Scope creep sang rack, multi-site, AI, container     |     High | Freeze Compute Down; extension chỉ sau W7 gate                        |
| R02 | Dữ liệu NetBox/runtime stale hoặc mapping sai     |     High | Source-of-truth rõ, timestamp/version, re-query, unknown không pass  |
| R03 | Race với Masakari/operator                          |     High | HA gate, external event id, lock, dedupe và revalidate                |
| R04 | Source chưa fence nhưng bị evacuate               | Critical | Blocking fencing evidence, không có override trong MVP               |
| R05 | Local ephemeral disk mất sau evacuation             |     High | Thu root disk type, risk flag, backup/shared storage policy            |
| R06 | Không đủ capacity                                 |     High | Partial plan, service priority, deficit/reason, không overcommit      |
| R07 | Scheduler từ chối target hoặc allocation race     |   Medium | Placement snapshot + headroom + Nova validate/claim + replan           |
| R08 | Network/storage dependency thiếu dữ liệu          |     High | Blocking/manual precheck, không assume PASS                           |
| R09 | Plan được duyệt nhưng state đổi               |     High | Plan hash/version, revalidation, stale→replan                         |
| R10 | Duplicate alert/execute                              |     High | Idempotency key, incident/VM locks, action tracking                    |
| R11 | API timeout/409/503                                  |   Medium | Error mapping, bounded retry/backoff, audit và operator escalation    |
| R12 | Credential/write action ảnh hưởng lab khác       |     High | Least privilege, allowlist, dry-run default, secret ngoài repo        |
| R13 | Generator synthetic không phù hợp model OpenStack |   Medium | Fixture nhỏ trước; extension VM→host/capacity/AZ có migration rõ |
| R14 | UI làm chậm core backend                           |   Medium | UI chỉ sau mock E2E; polling trước realtime nếu cần               |
| R15 | Demo live không ổn định                          |     High | Rehearsal, rollback, data riêng và video fallback                    |

## 21. Security, safety và audit

- Credentials lấy từ `clouds.yaml`, environment secret hoặc vault; không commit.
- Tách read-only credential cho collector/planner và write credential cho executor.
- Real executor bị feature flag + environment allowlist khóa mặc định.
- Không log token, password, full credential hoặc sensitive payload.
- Mọi write action lưu operator, plan hash, target, request/action id và result.
- Rate limit/authorization cho approve/execute; role operator khác role viewer.
- Không cho direct arbitrary OpenStack action qua API; chỉ action enum/policy cho phép.
- Fencing evidence và data-loss risk hiển thị rõ trước approve.
- Có kill switch/cancel cho action chưa gửi; action đã gửi phải theo state thật, không giả cancel.

## 22. Deliverables cuối

1. Source backend và UI tối thiểu.
2. Mock fixtures versioned và deterministic DR scenario generator/enricher.
3. API contract/OpenAPI và domain schema.
4. Architecture, sequence và state-machine diagrams.
5. Recovery/checklist policies, canonical `execution_runbook.yaml` và generated Ansible Playbook review-only.
6. Unit, contract, integration và E2E test suite.
7. Benchmark report FIFO/VM-priority/service-aware; manual baseline là mục riêng khi Track B chạy được.
8. Incident/Recovery Plan/Verification report mẫu.
9. Deployment guide, user guide và security/safety notes.
10. Demo script 10–15 phút và video fallback.
11. Software MVP acceptance report và OpenStack Lab Acceptance status tách riêng.
12. Limitations + backlog rack/cross-AZ/multi-site/AI/Terraform proposal.

## 23. Việc làm ngay sau khi duyệt plan này

Thứ tự không thay đổi:

1. Tạo `dr-system/` đúng cấu trúc Checkpoint 1.
2. Viết `netbox_mock.json` có `compute-01`, hai VM ảnh hưởng và candidate positive/negative.
3. Viết typed model `RecoveryContext`.
4. Viết `NetBoxService` đọc/validate/query fixture.
5. Viết `IncidentService` cho duy nhất `COMPUTE_DOWN`.
6. Viết `POST /incidents` và chuẩn hóa lỗi.
7. Viết 8 test case CTX-001…CTX-008.
8. Chạy test và curl, lưu expected output trong README.
9. Review Gate W2; chỉ sau đó mới thêm application mapping/planner.

## 24. Các câu hỏi cần xác minh, nhưng không chặn Checkpoint 1

Các câu sau phải được trả lời trước giai đoạn real OpenStack, không cần hỏi lại để bắt đầu mock backend:

- OpenStack release, Nova/Placement microversion và openstacksdk version của lab là gì?
- Compute/VM demo nào được phép power-off/fence/evacuate?
- Root disk là local, shared storage hay boot-from-volume?
- Ai/thiết bị nào cung cấp fencing evidence?
- Có all-project read permission và write permission nào?
- AZ/aggregate/host naming join với NetBox theo field nào?
- Network có provider/physnet/external firewall nào cần manual check?
- Application/Service/Component demo, health endpoint, `desired_replicas` và `min_healthy` cụ thể là gì?
- RTO target sẽ được đặt bao nhiêu sau manual baseline?
- P01–P09 có thể được cung cấp trước tuần 6 để chạy OpenStack Lab Acceptance hay phải ghi `BLOCKED_EXTERNAL`?

## 25. Backlog sau MVP

Ưu tiên sau khi Compute Down end-to-end đã hoàn thành:

1. Rack Down/multi-compute correlation và rack failure-domain exclusion.
2. Real NetBox adapter + sync/version policy.
3. OTel/Alertmanager intake và service heartbeat verification.
4. Reserved DR capacity benchmark so với shared capacity.
5. Preemption có allowlist, impact analysis và approval riêng.
6. MILP/CP-SAT optimizer và optimality-gap evaluation.
7. Cross-AZ/multi-site DR, network/firewall runbook sâu hơn.
8. Workflow repaired-host health check/re-enable.
9. Container/Kubernetes adapter nếu đề tài được mở scope chính thức.
10. AI chỉ dùng giải thích/risk advisory; không trở thành control plane mặc định.

## 26. Tài liệu tham khảo chính thức

- [Nova — Recover from a failed compute host](https://docs.openstack.org/api-guide/compute/server_concepts.html#recover-from-a-failed-compute-host)
- [Nova — Evacuate Server API](https://docs.openstack.org/api-ref/compute/#evacuate-server-evacuate-action)
- [Nova — Update Compute Service](https://docs.openstack.org/api-ref/compute/#update-compute-service)
- [Placement — Allocation Candidates](https://docs.openstack.org/api-ref/placement/#allocation-candidates)
- [Placement — Modeling with Provider Trees](https://docs.openstack.org/placement/latest/user/provider-tree.html)
- [Masakari — Host Monitor](https://docs.openstack.org/masakari-monitors/latest/hostmonitor.html)
- [Masakari — Failover Segments](https://docs.openstack.org/api-ref/instance-ha/#failoversegments-segments)
- [Masakari — Host Failure Configuration](https://docs.openstack.org/masakari/latest/configuration/sample_config.html#host-failure)
- [NetBox — Virtualization](https://netboxlabs.com/docs/netbox/features/virtualization/)
- [NetBox — Device Model](https://netboxlabs.com/docs/netbox/models/dcim/device/)
- [NetBox — Virtual Machine Model](https://netboxlabs.com/docs/netbox/models/virtualization/virtualmachine/)
- [OpenTelemetry — What is OpenTelemetry?](https://opentelemetry.io/docs/what-is-opentelemetry/)
- [OpenTelemetry — Resource](https://opentelemetry.io/docs/specs/otel/resource/)
- [OpenTelemetry — Service Resource Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/resource/service/)
- [OpenTelemetry — Host Resource Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/resource/host/)

---

**Điểm kiểm soát quan trọng nhất:** không chuyển sang Planning, AI hoặc recovery thật trước khi `POST /incidents` cho `compute-01 DOWN` tạo đúng Recovery Context và toàn bộ test Checkpoint 1 đã pass.
