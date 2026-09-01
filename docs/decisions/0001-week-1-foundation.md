# ADR-0001 — Nền tảng bài toán OpenStack DR Orchestrator

| Thuộc tính | Giá trị |
| --- | --- |
| Trạng thái quyết định | `Accepted` |
| Ngày ghi nhận | `01/09/2026` |
| Kỳ công việc | Tuần 1 — `24/08/2026–30/08/2026` |
| Gate tài liệu | `W1 = PASS` |
| OpenStack Lab Readiness | `BLOCKED_EXTERNAL` |
| Gate tiếp theo | W2 — `POST /incidents` → `RecoveryContext` |

## 1. Quyết định

> Xây dựng lớp DR Decision & Orchestration cho OpenStack, với kịch bản duy nhất của MVP đầu là `COMPUTE_DOWN`, nhằm xác định workload/service bị ảnh hưởng, lập kế hoạch có kiểm soát, phê duyệt, thực thi và kiểm chứng phục hồi trên hạ tầng còn khả dụng.

Mục tiêu cuối là khôi phục mức hoạt động cần thiết của service/application. VM là recovery unit của MVP; compute host, rack và AZ là nguồn sự cố hoặc failure domain. Vòng đời khắc phục thiết bị vật lý không thuộc control plane của hệ thống này.

Tuần 1 chỉ khóa bài toán, ranh giới trách nhiệm, nguồn dữ liệu, lifecycle và điều kiện tích hợp. Tuần 1 không thay đổi runtime contract, không tạo backend và không tạo fixture của Tuần 2.

## 2. Phạm vi đã khóa

### 2.1 Hai mức vertical slice

**Checkpoint đầu tiên — W2, read-only:**

```text
compute-01 DOWN
      ↓
POST /incidents
      ↓
đọc aggregate fixture data/netbox_mock.json
      ↓
xác định source rack/AZ, affected VMs và candidate pool sơ bộ
      ↓
RecoveryContext
```

Checkpoint này không dùng API OpenStack/NetBox/OTel thật, không persistence, không planner, không approval và không thực thi recovery.

**Software MVP:** tiếp tục đúng incident type `COMPUTE_DOWN` qua:

```text
Context → Impact → Planning → Pre-check → Approval → Mock Execute → Verification
```

### 2.2 In scope của Software MVP

- `COMPUTE_DOWN` là incident type duy nhất.
- Mock topology/runtime và application mapping có version, timestamp và deterministic ordering.
- Application-aware impact và service-aware batch planning.
- Persistence, audit, plan version/hash, approval, dry-run và mock execution.
- Fencing gate, idempotency, reconciliation và verification nhiều lớp.
- Canonical YAML runbook, Ansible Playbook review-only và War-Room UI tối thiểu.
- Real read-only discovery khi lab đáp ứng prerequisite; real evacuation có acceptance gate riêng.

### 2.3 Out of scope của MVP đầu

- Rack Down, multi-compute simultaneous failure, cross-AZ và multi-site DR.
- `VM_FAILURE`, application-only failure và host maintenance/drain như workflow chính.
- Repaired-host health-check/re-enable workflow.
- Container/Kubernetes relocation.
- Stateful leader/quorum/replication-lag recovery.
- Preemption tự động, power/PDU optimization hoặc thay đổi external firewall tự động.
- AI/LLM làm control plane hoặc tự quyết định recovery action.

Các nội dung trên chỉ được xuất hiện dưới nhãn `Future`, `Extension` hoặc `Backlog`. Không nội dung nào được dùng để mở rộng acceptance của MVP đầu.

## 3. Reuse/build matrix

| Dependency | Reuse | Phần hệ thống xây | Không làm/ranh giới |
| --- | --- | --- | --- |
| Nova | Live state của compute/VM, all-project server placement, `EVACUATE`, `START`, scheduler validation và action/request ID | Runtime adapter, normalization, action orchestration, revalidation và audit | Không thay Nova Scheduler; không coi `forced_down` là fencing; không live-migrate từ dead host |
| Placement | Resource provider inventory, usage, traits, aggregates và allocation candidates | Snapshot adapter, batch ranking theo service/failure domain và rejected reasons | Không tự ghi `PUT /allocations`; Nova Scheduler vẫn claim/validate cuối |
| Masakari | Notification, failover segment, native host-failure result và recovery workflow làm baseline/integration tùy chọn | Native-HA observation gate, dedupe, result correlation và service-level verification | Không bắt buộc ở mock checkpoint; không phát recovery trùng với workflow đang chạy hoặc đã thành công |
| NetBox | Site, location, rack, device, cluster, VM/IP inventory và topology vật lý | Topology adapter, identity join và failure-domain enrichment | Không dùng làm live state/capacity truth; không coi aggregate fixture là raw export |
| OpenTelemetry | Trace/metric/log signal và resource identity để correlate host/service evidence | Telemetry adapter, evidence normalization và health correlation | Không coi OTel là alert engine, CMDB hoặc observability backend |
| Keystone/service catalog | Authentication, project scope, service endpoints và region discovery | Credential boundary, endpoint discovery và lab allowlist | Không hard-code endpoint hoặc commit secret |
| Neutron | Port, binding, fixed IP, security group, network/physnet runtime | Network pre-check và verification evidence | Không tự thay external firewall trong MVP |
| Cinder/storage policy | Volume attachment, volume state và storage capability/policy | Storage pre-check, root-disk classification và data-loss risk | Không suy luận RPO chỉ từ evacuation |
| CMDB/application catalog | Application/service/component mapping, priority, owner, `min_healthy` và RTO policy | Versioned application graph adapter và service objective | Không lấy telemetry attribute làm authority duy nhất |
| Monitoring/alerting | Trigger, alert identity, timestamps và corroborating health signal | Incident normalization, evidence window và dedupe | Một alert đơn lẻ không đủ để dispatch write action |
| Fencing provider | Hard power-off hoặc isolation proof từ BMC/PDU/network/storage control | Evidence adapter, freshness/policy validation và blocking pre-check | Orchestrator không giả lập evidence; `disable scheduling`/`forced_down` không thay thế fencing |

Masakari và OTel là optional integration đối với mock checkpoint. Khi được bật, cả hai phải đi qua native-HA/deduplication gate trước khi planner được phép sinh write plan.

## 4. Audit workspace và dữ liệu synthetic

### 4.1 Workspace tại thời điểm chốt W1

- Git đang track 6 file: `README.md`, `plan_full.md` và 4 file trong bộ synthetic NetBox.
- Chưa có backend DR, package manifest, test suite, database, `data/netbox_mock.json` hoặc application fixture.
- `generate_viettel_demo.py` qua kiểm tra cú pháp Python; `install.sh` qua `bash -n`.
- W1 không tạo runtime artifact và không thay đổi generator.

### 4.2 Bằng chứng từ bộ synthetic NetBox

- Generator nhắm NetBox `3.1.7`, dùng seed cố định `20260826`, định nghĩa 5 site và hỗ trợ scale theo target trong YAML.
- Có site, rack, switch, physical hypervisor, cluster, VM, IP/VLAN, database service và hard-case metadata.
- Cluster type đang là synthetic `vSphere`.
- VM được gắn vào cluster nhưng không được pin vào một hypervisor cụ thể.
- Không có Nova live state, compute enabled/maintenance state, total/used/free capacity, OpenStack AZ mapping, application priority, `min_healthy` hoặc `COMPUTE_DOWN` scenario trực tiếp.

### 4.3 Quyết định sử dụng dữ liệu

Không thay đổi generator ở W1 hoặc W2 checkpoint đầu. W2 tạo một JSON nhỏ, deterministic, theo contract đã chốt. Tên file là `netbox_mock.json` để giữ contract demo, nhưng nội dung là **aggregate demo fixture** mô phỏng kết quả join giữa topology NetBox và runtime OpenStack, không phải raw NetBox export.

Generator chỉ được mở rộng sau khi contract fixture nhỏ ổn định và cần dataset medium/large để benchmark collector/planner.

## 5. Source-of-truth matrix

| Dữ liệu/quyết định | Mock đầu tiên | Source of truth tích hợp | Owner vai trò | Freshness/evidence | Khi `UNKNOWN` |
| --- | --- | --- | --- | --- | --- |
| Incident trigger | Request giả lập | Monitoring/alerting; Masakari notification nếu có | Monitoring operator | Event ID, `detected_at`, producer và raw reference | Giữ `CONFIRMING`; không dispatch |
| Compute live/up/down/enabled | Aggregate fixture | Nova service/hypervisor API | OpenStack compute admin | Snapshot timestamp và Nova request ID | `CONTEXT_INCOMPLETE` hoặc blocking pre-check |
| VM đang ở compute nào | Aggregate fixture | Nova all-project server inventory/extended attrs | OpenStack compute admin | Server UUID, host và observed timestamp | Không suy luận từ cluster NetBox |
| CPU/RAM/disk candidate | Aggregate fixture | Placement inventory, usage và allocation candidates | OpenStack capacity admin | Placement generation/microversion và timestamp | Candidate bị loại |
| Site/rack/failure domain | Aggregate fixture | NetBox/DCIM | DCIM owner | Object ID, last-updated/version và join key | Warning hoặc block theo policy |
| OpenStack AZ/aggregate | Aggregate fixture | Nova AZ/aggregate + explicit NetBox mapping | OpenStack compute admin | Mapping version và observed timestamp | Không giả định từ rack/site |
| Network/port/SG/physnet | Field mock tối thiểu | Neutron | Network admin | Port/binding state và request ID | Blocking trước execute |
| Volume/root/shared storage | Field mock tối thiểu | Cinder + storage policy/test evidence | Storage admin | Volume attachment, root type và assessment timestamp | `MANUAL_REQUIRED`; không evacuate |
| Application/service mapping | Application fixture | CMDB/service catalog/policy DB | Service owner | Catalog/policy version và owner | Context incomplete; không tự gán priority |
| Service health evidence | Synthetic check | Monitoring/OTel + approved health endpoint | Service owner/SRE | Signal window, resource identity và check evidence | Không kết luận healthy/success |
| Priority/RTO/checklist | Versioned YAML | Policy DB/CMDB | DR policy owner | Policy version/hash | Không tự dùng default production |
| Fencing/isolation | Synthetic boolean chỉ cho mock test | BMC/PDU hoặc approved network/storage isolation system | Infrastructure operator | Provider, target, result, actor và fresh timestamp | Blocking; không có override trong MVP |
| Approval | Synthetic operator record | Internal DR database/identity provider | DR operator | Operator ID/role, plan ID/version/hash và timestamp | Không execute |

Snapshot dùng cho plan và execute phải có `observed_at`, source version/identifier và policy-defined maximum age. Giá trị `UNKNOWN` không bao giờ được nâng thành `PASS`.

## 6. Glossary chuẩn

| Thuật ngữ | Định nghĩa dùng trong dự án |
| --- | --- |
| Compute Host | Máy vật lý/hypervisor chạy `nova-compute`; không đồng nghĩa với Nova Server |
| Nova Server / VM | Virtual machine do Nova quản lý; recovery unit của MVP |
| Incident | Bản ghi một sự cố đã được normalize, có identity, evidence và lifecycle |
| `COMPUTE_DOWN` | Incident type duy nhất của MVP đầu, biểu diễn compute host nguồn không khả dụng |
| Recovery Unit | Đơn vị mà executor thao tác; trong MVP là VM |
| Protected Object | Service/application cần đạt lại objective; không nhất thiết mọi VM đều phải được phục hồi |
| Recovery Context | Snapshot hợp nhất incident, runtime, topology, application impact và candidate pool |
| Failure Domain | Phạm vi tài nguyên có thể hỏng cùng nguyên nhân, như host/rack/AZ |
| Blast Radius | Tập resource và service bị ảnh hưởng trực tiếp hoặc gián tiếp |
| Native HA Gate | Cửa kiểm soát chờ/quan sát Masakari hoặc HA hiện hữu; service healthy thì `NO_ACTION` |
| Fencing | Bằng chứng host/VM nguồn không thể tiếp tục chạy hoặc ghi vào shared resource |
| `forced_down` | Cờ Nova cho biết compute được operator đánh dấu down; không phải fencing evidence |
| Candidate Pool | Tập compute sơ bộ có thể xem xét; chưa phải target plan cuối |
| Recovery Plan | Đề xuất versioned gồm objective, ordered action, target, reason, risk và expected checks |
| Pre-check | Kiểm tra blocking/non-blocking trước approval và được revalidate trước dispatch |
| Approval | Quyết định operator gắn đúng `plan_id + version + hash` |
| Staleness | Context/capacity/state thay đổi làm plan hoặc approval cũ mất hiệu lực |
| Idempotency | Cùng logical request/action không tạo thực thi trùng |
| Reconciliation | Query trạng thái thật sau timeout/crash/response bất định trước khi retry |
| Verification | Kiểm tra compute, storage, network và application trước khi kết luận incident |
| RTO/RPO | Mục tiêu thời gian phục hồi/lượng dữ liệu có thể mất; evacuation không tự bảo đảm RPO |
| `BLOCKED_EXTERNAL` | Trạng thái readiness/acceptance khi lab thiếu prerequisite; không phải runtime incident state |

Quy ước field: `source` trong Recovery Context là source compute/failure domain; nguồn phát alert dùng `reported_by` để tránh nhập nhằng.

## 7. Final state machine

Không dùng một enum chung cho Incident, Plan, Execution và Action. Mỗi transition phải lưu actor, timestamp, source state, target state, reason và evidence.

### 7.1 Incident lifecycle

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

Incident terminal states: `NO_ACTION`, `SUCCESS`, `PARTIAL`, `FAILED`, `MANUAL_REQUIRED`.

### 7.2 Plan lifecycle

```text
DRAFT → VALIDATING
          ├── no accepted action → NO_FEASIBLE_PLAN
          ├── safe subset only   → PARTIAL_PLAN
          └── full objective     → PLANNED

PARTIAL_PLAN / PLANNED → PRECHECKING
                           ├── fail → PRECHECK_FAILED
                           └── pass → WAITING_APPROVAL → APPROVED / REJECTED

APPROVED → CONSUMED_BY_EXECUTION
         └── context drift before dispatch → STALE
```

`REPLAN` không phải persisted state. Replan là command/process tạo context và plan version mới; approval cũ không được tái sử dụng. `PARTIAL_PLAN` chỉ được approve khi có ít nhất một action an toàn và policy cho phép partial recovery.

### 7.3 Execution lifecycle

```text
PENDING → REVALIDATING
             ├── drift → BLOCKED_STALE
             └── pass  → RUNNING → VERIFYING
                                      ├── SUCCESS
                                      ├── PARTIAL
                                      ├── FAILED
                                      └── MANUAL_REQUIRED
```

### 7.4 Per-action lifecycle

```text
PENDING → DISPATCHING → ACCEPTED → POLLING → SUCCEEDED / FAILED
              └── response bất định → UNKNOWN → RECONCILING
                                                   ├── ACCEPTED / POLLING
                                                   ├── SUCCEEDED / FAILED
                                                   └── MANUAL_REQUIRED
```

`UNKNOWN` là transient state và không bao giờ được coi là success. `BLOCKED_EXTERNAL` không xuất hiện trong bốn lifecycle; trạng thái đó thuộc báo cáo lab readiness/acceptance khi workflow thực tế chưa đủ điều kiện để bắt đầu.

## 8. OpenStack lab prerequisite register

Tại ngày ghi nhận, workspace không chứa evidence lab đáng tin cậy. Vì vậy P01–P09 đều giữ `UNKNOWN`; không điền giá trị demo thay cho sự thật vận hành.

| ID | Prerequisite | Status | Owner vai trò | Evidence bắt buộc | Hạn chốt | Blocking effect |
| --- | --- | --- | --- | --- | --- | --- |
| P01 | Keystone account/policy: read all-project inventory và write recovery chỉ trên allowlisted lab | `UNKNOWN` | OpenStack IAM/admin | Project/role, policy probe, allowed resource list; không lưu secret | Trước real adapter/write | Chỉ mock/read-only; real executor disabled |
| P02 | Service catalog endpoints, region, OpenStack release, Nova/Placement min-max microversion và openstacksdk version | `UNKNOWN` | OpenStack platform admin | Sanitized discovery output và compatibility record | Trước real adapter | Không pin client version; real executor disabled |
| P03 | Root disk/local ephemeral/shared storage/boot-from-volume behavior | `UNKNOWN` | Storage admin | Per-workload assessment và manual evacuation test evidence | Trước evacuation | `MANUAL_REQUIRED`; action bị block |
| P04 | Approved fencing/power-off or isolation provider | `UNKNOWN` | Infrastructure operator | Provider, target, actor, result và fresh timestamp | Trước real E2E | Không evacuate; không override |
| P05 | Target capacity/headroom, traits, aggregates, AZ và scheduler acceptance | `UNKNOWN` | Capacity/compute admin | Placement snapshot/generation và Nova validation result | Trước W6 happy case | Chỉ partial/safe-stop hoặc block |
| P06 | NetBox↔Nova identity join và application/service/priority mapping | `UNKNOWN` | DCIM + service owner | Join-key contract, mapping version, owner và completeness report | Trước W3 gate | Context incomplete; planner blocked |
| P07 | Target network/physnet/SG/external firewall và storage reachability | `UNKNOWN` | Network + storage admin | Port/binding/path test và manual dependency confirmation | Trước W4/W6 | Blocking pre-check hoặc manual task |
| P08 | Maintenance window, named supervisor, kill switch và rollback/manual recovery runbook | `UNKNOWN` | Change manager + DR operator | Approved change record và rollback rehearsal | Trước failure injection | Không power-off/fence host thật |
| P09 | Demo workload, `/health`, `desired_replicas`, `min_healthy`, marker/checksum và RTO target | `UNKNOWN` | Service owner/SRE | Versioned workload manifest, health contract, marker procedure và baseline | Trước W5/W6 | Không claim service recovery, integrity hoặc RTO compliance |

### 8.1 Microversion rules phải xác minh trong P02

- Nếu chỉ định target host cho Nova evacuation, selected Nova microversion phải `>=2.29` để scheduler validate target.
- Executor không gửi `force`; từ microversion `2.68`, Nova không còn chấp nhận field này.
- Từ microversion `2.95`, evacuated server giữ trạng thái dừng ở destination; plan phải có bước `START` riêng nếu policy yêu cầu workload chạy lại.
- Host nguồn phải thực sự được fence và phải được báo down hoặc marked `forced_down` phù hợp policy trước evacuation.
- Placement allocation candidates yêu cầu Placement API `>=1.10`.
- Client phải discover min/max từ endpoint và pin version đã kiểm chứng; không dùng “latest” hoặc hard-code service URL.

Tham khảo chính thức: [Nova Evacuate API](https://docs.openstack.org/api-ref/compute/#evacuate-server-evacuate-action), [Nova failed-compute recovery](https://docs.openstack.org/api-guide/compute/server_concepts.html#recover-from-a-failed-compute-host), [Placement allocation candidates](https://docs.openstack.org/api-ref/placement/#allocation-candidates), [Masakari recovery workflow](https://docs.openstack.org/masakari/latest/configuration/recovery_workflow_sample_config.html), [NetBox virtualization](https://netboxlabs.com/docs/netbox/features/virtualization/) và [OpenTelemetry overview](https://opentelemetry.io/docs/what-is-opentelemetry/).

## 9. Gate W1 acceptance record

| Tiêu chí | Evidence | Kết quả |
| --- | --- | --- |
| Mục tiêu là phục hồi workload/service, không phải xử lý thiết bị vật lý | Sections 1–2 và glossary | `PASS` |
| Scenario duy nhất của MVP đầu là `COMPUTE_DOWN` | Sections 1–2 | `PASS` |
| Reuse/build của Nova, Placement, Masakari, NetBox và OTel rõ ràng | Section 3 | `PASS` |
| Mọi external dependency có owner/source/unknown behavior | Sections 3 và 5 | `PASS` |
| Workspace và synthetic dataset đã được audit | Section 4 | `PASS` |
| Source-of-truth, glossary và bốn lifecycle đã được khóa | Sections 5–7 | `PASS` |
| P01–P09 có status, owner, evidence, deadline và blocking effect | Section 8 | `PASS` |
| Lab có đủ evidence để chạy real evacuation | P01–P09 đều `UNKNOWN` | `BLOCKED_EXTERNAL` |

**Kết luận:** `Gate W1 = PASS`. `OpenStack Lab Readiness = BLOCKED_EXTERNAL`. Gate tiếp theo duy nhất là W2: triển khai read-only `compute-01 DOWN → POST /incidents → RecoveryContext`; chưa được mở Planning, real adapter hoặc recovery action.

