# NetBox 3.1.7 Viettel-like Synthetic Datacenter Generator — Hard Cases

Bản này mở rộng generator bằng **scenario-driven hard cases**, không random version tự do.

## Hard-case ground truth

Generator tạo Custom Fields trên `Device`, `VirtualMachine`, `Service`:

- `syn_asset_class`
- `syn_software_name`
- `syn_software_version`
- `syn_case`: `normal | legacy | vulnerable | legacy_vulnerable | malformed`
- `syn_eol`
- `syn_known_vulnerable`
- `syn_vulnerability_ids`
- `syn_failure_mode`: `none | timeout | auth_failure | connection_refused | port_mismatch | tls_expired | version_parse_error`

Các `SYN-VULN-*` trong YAML là **ID giả lập**, dùng làm ground truth test. Chúng không khẳng định một CVE thật. Nếu muốn test CVE thật, thay catalog bằng mapping nội bộ/CVE đã xác minh.

### Ví dụ case được sinh

Switch:

```text
Cisco IOS XE 17.9.5   -> normal
Cisco IOS XE 16.6.10  -> legacy/EOL
Cisco IOS XE 17.3.1   -> vulnerable (synthetic ground truth)
Juniper 11.4R13       -> legacy_vulnerable
```

VM/host:

```text
Rocky Linux 9.3       -> normal
CentOS 6.10           -> legacy/EOL
CentOS 4.9            -> legacy_vulnerable
Windows Server 2008   -> legacy_vulnerable
```

Service/database:

```text
PostgreSQL 15.5       -> normal
PostgreSQL 9.6.24     -> legacy_vulnerable
MariaDB 5.5.68        -> legacy_vulnerable
```

Runtime faults được sinh độc lập với version:

```text
timeout
auth_failure
connection_refused
port_mismatch
tls_expired
version_parse_error
```

Tỷ lệ được cấu hình trong `viettel_demo.yaml`. Generator dùng apportionment để đảm bảo đúng số lượng theo weight (ở scale đủ lớn), sau đó seed chỉ xáo vị trí case.

## Query hard cases

```bash
python manage.py nbshell
```

```python
from dcim.models import Device
from virtualization.models import VirtualMachine
from ipam.models import Service

# Switch legacy/vulnerable
Device.objects.filter(
    device_role__slug='syn-network-switch',
    custom_field_data__syn_case='legacy_vulnerable',
)

# CentOS 4 VM
VirtualMachine.objects.filter(
    custom_field_data__syn_software_name='CentOS',
    custom_field_data__syn_software_version='4.9',
)

# Service có runtime fault
Service.objects.filter(
    description__startswith='SYN:database',
).exclude(custom_field_data__syn_failure_mode='none')

# Service sai port
Service.objects.filter(
    custom_field_data__syn_failure_mode='port_mismatch',
)
```

## Chạy nhanh

```bash
./install.sh /opt/netbox
cd /opt/netbox/netbox
source /opt/netbox/venv/bin/activate

python manage.py generate_viettel_demo \
  --config /opt/netbox/synthetic/viettel_demo.yaml \
  --scale 0.01 \
  --reset
```

Sau khi sinh, command tự in summary hard cases.

---

# NetBox 3.1.7 Viettel-like Synthetic Datacenter Generator

This package contains a Django management command for **NetBox v3.1.7**.
It creates a deterministic synthetic dataset spanning five Vietnam datacenter sites:

- Hòa Lạc
- Pháp Vân
- Bình Dương
- Hoàng Hoa Thám (TP.HCM)
- Đà Nẵng

Full profile targets:

- 50,000 network switches
- 8,000 physical hypervisors
- 50,000 VMs
- 2,000 database services
- 2,000,000 IP addresses
- 4,000 racks
- 500 clusters
- 5,000 VLANs

## Why this is a management command

For millions of rows, do not create a multi-GB Django JSON fixture. Generate once in a dedicated test PostgreSQL database, validate it, then capture a PostgreSQL dump for repeatable restores.

## NetBox 3.1.7 compatibility assumptions

This code is written for the 3.1.7 data model:

- `Device.device_role` is used (not the newer `role` name).
- `Prefix.site` exists in 3.1.7.
- `VirtualMachine.cluster` is mandatory.
- `IPAddress` is assigned to `dcim.Interface` or `virtualization.VMInterface` via ContentType + object ID.
- Databases are represented with `ipam.Service` because stock NetBox 3.1.7 has no Database model.

## Install

Assume your NetBox checkout is `/opt/netbox` and the directory containing `manage.py` is `/opt/netbox/netbox`.

Copy the command:

```bash
cp dcim/management/commands/generate_viettel_demo.py \
  /opt/netbox/netbox/dcim/management/commands/
```

Copy the config wherever convenient, for example:

```bash
mkdir -p /opt/netbox/synthetic
cp viettel_demo.yaml /opt/netbox/synthetic/
```

Activate the NetBox virtualenv and enter the directory containing `manage.py`:

```bash
cd /opt/netbox/netbox
source /opt/netbox/venv/bin/activate
```

Verify the command is visible:

```bash
python manage.py help generate_viettel_demo
```

## IMPORTANT: use a disposable/test database

Do not run the full generator against a production NetBox database.

Take a backup first if the instance contains anything important.

## Smoke test first

Generate ~0.1% of the target dataset:

```bash
python manage.py generate_viettel_demo \
  --config /opt/netbox/synthetic/viettel_demo.yaml \
  --scale 0.001
```

Expected approximate smoke-test size:

- 50 switches
- 8 hypervisors
- 50 VMs
- 2 DB services
- 2,000 IPs
- at least 5 racks/clusters/VLANs

Inspect NetBox UI and validate counts:

```bash
python manage.py generate_viettel_demo \
  --config /opt/netbox/synthetic/viettel_demo.yaml \
  --scale 0.001 \
  --validate-only
```

## Reset smoke data

```bash
python manage.py generate_viettel_demo \
  --config /opt/netbox/synthetic/viettel_demo.yaml \
  --scale 0.001 \
  --reset \
  --validate-only
```

The reset operation deletes rows marked/named by this generator. It is still intended for a dedicated test DB only.

## Medium test

Before 2 million IPs, use 1%:

```bash
python manage.py generate_viettel_demo \
  --config /opt/netbox/synthetic/viettel_demo.yaml \
  --scale 0.01 \
  --reset
```

This produces roughly 20,000 IPs, 500 switches and 500 VMs.

## Full dataset

When the smoke/medium profiles work:

```bash
python manage.py generate_viettel_demo \
  --config /opt/netbox/synthetic/viettel_demo.yaml \
  --scale 1.0 \
  --reset
```

Full generation uses `bulk_create()` for the large object sets and creates IP addresses in batches of 5,000.

## Fast topology-only test

To test Device/VM discovery without creating the remaining unassigned IP pool:

```bash
python manage.py generate_viettel_demo \
  --config /opt/netbox/synthetic/viettel_demo.yaml \
  --scale 1.0 \
  --reset \
  --no-ip-pool
```

It will still assign one private primary IPv4 address to every generated Device and VM interface.

## Database representation

NetBox 3.1.7 core does not provide a Database model, so the generator creates `ipam.Service` objects such as:

```text
db-postgresql-000001   tcp/5432   -> syn-vm-hl-0000001
db-mariadb-000002      tcp/3306   -> syn-vm-hl-0000002
```

If your internal NetBox/DCIM fork has a dedicated Database model, edit only `_create_databases()` in `generate_viettel_demo.py`.

Recommended mapping:

```text
Database.name        <- db-<engine>-<number>
Database.type/engine <- PostgreSQL/MariaDB/MySQL/Oracle/MSSQL/MongoDB
Database.host        <- generated VirtualMachine
Database.port        <- engine default port
Database.status      <- active
Database.version     <- deterministic/randomized supported version
```

## IP design

Private synthetic pools use RFC1918 space:

```text
Hòa Lạc       10.0.0.0/11
Pháp Vân      10.32.0.0/11
Bình Dương    10.64.0.0/11
HHT HCM       10.96.0.0/11
Đà Nẵng       10.128.0.0/11
```

The "Internet-facing" simulation uses 100.64.0.0/10 subranges. This is intentionally **not real public IPv4 space**. It is safe synthetic CGNAT/shared space carrying Internet-facing semantics for discovery/testing.

If your application specifically requires `ipaddress.ip_address(x).is_global == True`, implement a separate test-only address abstraction rather than injecting randomly selected real public addresses.

## Capture the generated DB as the reusable fixture

After a successful full generation, use a PostgreSQL custom-format dump:

```bash
pg_dump -Fc -U netbox -d netbox > viettel-synthetic-netbox317.dump
```

Restore into a fresh test database:

```bash
createdb -U netbox netbox_synthetic
pg_restore -U netbox -d netbox_synthetic viettel-synthetic-netbox317.dump
```

This is the recommended large-scale fixture workflow. Restoring a PostgreSQL dump is much more practical than `loaddata` for millions of rows.

## Useful validation queries

From NetBox shell:

```bash
python manage.py nbshell
```

```python
from dcim.models import Device
from virtualization.models import VirtualMachine
from ipam.models import IPAddress, Service

Device.objects.filter(device_role__slug='syn-network-switch').count()
VirtualMachine.objects.filter(name__startswith='syn-vm-').count()
IPAddress.objects.filter(description__startswith='SYN:').count()
Service.objects.filter(description__startswith='SYN:database').count()
```

Platform distribution:

```python
from django.db.models import Count
Device.objects.filter(device_role__slug='syn-network-switch') \
    .values('platform__slug') \
    .annotate(n=Count('id')) \
    .order_by('platform__slug')
```

Site distribution:

```python
Device.objects.filter(device_role__slug='syn-network-switch') \
    .values('site__name') \
    .annotate(n=Count('id')) \
    .order_by('site__name')
```

## Performance notes

For the full profile:

1. Run PostgreSQL locally or over a low-latency network.
2. Ensure there is enough free disk for PostgreSQL data, WAL, indexes, and the dump.
3. Generate on a test DB with no concurrent NetBox traffic.
4. Start with `--scale 0.001`, then `0.01`, then `1.0`.
5. Keep the generated `pg_dump` so later test runs only need restore.

The command intentionally uses bulk operations. `bulk_create()` does not execute the normal per-object NetBox `save()` behavior/signals. Therefore the code explicitly creates Device and VM interfaces rather than relying on DeviceType component templates.
