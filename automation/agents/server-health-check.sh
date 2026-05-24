#!/usr/bin/env bash
set -u

META="http://169.254.169.254/latest"
TOKEN="$(curl -s -m 2 -X PUT "$META/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")"

get_meta() {
  local path="$1"
  if [ -n "${TOKEN:-}" ]; then
    curl -s -m 2 -H "X-aws-ec2-metadata-token: $TOKEN" "$META/meta-data/$path"
  else
    curl -s -m 2 "$META/meta-data/$path"
  fi
}

echo "===== EC2 INSTANCE REPORT ====="
echo

echo "[Host]"
hostname
echo "FQDN: $(hostname -f 2>/dev/null || true)"
echo "Kernel: $(uname -a)"
echo

echo "[OS]"
cat /etc/os-release 2>/dev/null | grep -E '^(PRETTY_NAME|NAME|VERSION)=' || true
echo

echo "[CPU]"
lscpu 2>/dev/null | grep -E 'Model name:|CPU\(s\):|Thread\(s\) per core:|Core\(s\) per socket:|Socket\(s\):|Architecture:' || true
echo

echo "[Memory]"
free -h
echo

echo "[Disks / EBS]"
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE
echo
df -hT
echo

echo "[Network - Local]"
echo "Private IP(s): $(hostname -I 2>/dev/null || true)"
ip -brief addr 2>/dev/null || ip a
echo

echo "[EC2 Metadata]"
INSTANCE_ID="$(get_meta instance-id 2>/dev/null || true)"
INSTANCE_TYPE="$(get_meta instance-type 2>/dev/null || true)"
AMI_ID="$(get_meta ami-id 2>/dev/null || true)"
AZ="$(get_meta placement/availability-zone 2>/dev/null || true)"
MAC="$(get_meta mac 2>/dev/null || true)"
LOCAL_IPV4="$(get_meta local-ipv4 2>/dev/null || true)"
PUBLIC_IPV4="$(get_meta public-ipv4 2>/dev/null || true)"
LOCAL_HOSTNAME="$(get_meta local-hostname 2>/dev/null || true)"
PUBLIC_HOSTNAME="$(get_meta public-hostname 2>/dev/null || true)"
SUBNET_ID="$(get_meta network/interfaces/macs/$MAC/subnet-id 2>/dev/null || true)"
VPC_ID="$(get_meta network/interfaces/macs/$MAC/vpc-id 2>/dev/null || true)"
SEC_GROUPS="$(get_meta security-groups 2>/dev/null || true)"

echo "Instance ID: ${INSTANCE_ID:-N/A}"
echo "Instance Type: ${INSTANCE_TYPE:-N/A}"
echo "AMI ID: ${AMI_ID:-N/A}"
echo "Availability Zone: ${AZ:-N/A}"
echo "Local Hostname: ${LOCAL_HOSTNAME:-N/A}"
echo "Public Hostname: ${PUBLIC_HOSTNAME:-N/A}"
echo "Private IPv4: ${LOCAL_IPV4:-N/A}"
echo "Public IPv4: ${PUBLIC_IPV4:-N/A}"
echo "MAC: ${MAC:-N/A}"
echo "Subnet ID: ${SUBNET_ID:-N/A}"
echo "VPC ID: ${VPC_ID:-N/A}"
echo "Security Groups:"
printf '%s\n' "${SEC_GROUPS:-N/A}"
echo

echo "[Top memory consumers]"
ps -eo pid,ppid,cmd,%mem,%cpu --sort=-%mem | head
echo

echo "[Top CPU consumers]"
ps -eo pid,ppid,cmd,%mem,%cpu --sort=-%cpu | head
echo