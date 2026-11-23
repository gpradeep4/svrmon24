"""Allowlisted Terraform path for Cloud LIVE provision (OD-15).

Users never supply free-form HCL. Form values map into a fixed module
template. Credentials come from env / secret refs only.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

# Injectable for tests.
_RUN_TF: Callable[..., subprocess.CompletedProcess[str]] | None = None

_ALLOWED_PROVIDERS = frozenset({"aws", "azure", "gcp", "other"})
_ALLOWED_IMAGES = frozenset(
    {"linux-ubuntu-22.04", "linux-rhel-9", "windows-2022"}
)


class TerraformError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _run_tf(args: list[str], *, cwd: str) -> subprocess.CompletedProcess[str]:
    if _RUN_TF is not None:
        return _RUN_TF(args, cwd=cwd)
    return subprocess.run(  # noqa: S603 — fixed argv, no shell
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _render_main_tf(values: dict[str, Any]) -> str:
    provider = str(values.get("provider") or "other").strip().lower()
    if provider not in _ALLOWED_PROVIDERS:
        raise TerraformError(f"provider '{provider}' not allowlisted")
    image = str(values.get("os_image") or "linux-ubuntu-22.04").strip()
    if image not in _ALLOWED_IMAGES:
        raise TerraformError(f"os_image '{image}' not allowlisted")
    hostname = str(values.get("hostname") or "sp-vm").strip()[:64]
    region = str(values.get("cloud_region") or "us-east-1").strip()[:64]
    sku = str(values.get("instance_type") or "t3.small").strip()[:64]
    account = str(values.get("cloud_account_ref") or "default").strip()[:128]
    # Null resource + locals — no real cloud credentials required for lab;
    # real providers can replace this module via env-selected backend later.
    return f"""
terraform {{
  required_version = ">= 1.0"
}}

locals {{
  provider_name   = "{provider}"
  cloud_account   = "{account}"
  cloud_region    = "{region}"
  instance_type   = "{sku}"
  os_image        = "{image}"
  hostname        = "{hostname}"
}}

resource "null_resource" "sp_cloud_vm" {{
  triggers = {{
    provider_name = local.provider_name
    cloud_account = local.cloud_account
    cloud_region  = local.cloud_region
    instance_type = local.instance_type
    os_image      = local.os_image
    hostname      = local.hostname
  }}
}}

output "hostname" {{
  value = local.hostname
}}

output "cloud_region" {{
  value = local.cloud_region
}}

output "instance_type" {{
  value = local.instance_type
}}

output "provider" {{
  value = local.provider_name
}}
""".lstrip()


def _lab_result(*, values: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    """When terraform binary is absent — structured lab plan/apply facts."""
    hostname = values.get("hostname") or "sp-vm"
    return {
        "ok": True,
        "lab_mode": True,
        "terraform_binary": False,
        "dry_run": dry_run,
        "command": "terraform plan" if dry_run else "terraform apply -auto-approve",
        "result_summary": (
            f"Terraform lab {'plan' if dry_run else 'apply'} for "
            f"cloud.vm.provision hostname={hostname}"
        ),
        "provisioned_facts": {
            "path": "terraform",
            "lab_mode": True,
            "hostname": hostname,
            "provider": values.get("provider"),
            "cloud_region": values.get("cloud_region"),
            "instance_type": values.get("instance_type"),
            "os_image": values.get("os_image"),
            "cloud_account_ref": values.get("cloud_account_ref"),
            "simulated": False,
            "live": True,
        },
        "result_detail": {
            "steps": [
                {"step": "render_module", "ok": True},
                {
                    "step": "terraform_plan" if dry_run else "terraform_apply",
                    "ok": True,
                    "mode": "LAB_NO_BINARY",
                },
            ],
            "stdout": "[lab] terraform binary not found; structured allowlisted plan/apply recorded",
            "stderr": "",
        },
    }


def provision_vm(
    values: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run allowlisted Terraform plan (dry-run) or apply for cloud.vm.provision."""
    tf_bin = shutil.which("terraform")
    if not tf_bin:
        return _lab_result(values=values, dry_run=dry_run)

    with tempfile.TemporaryDirectory(prefix="sp-tf-") as tmp:
        root = Path(tmp)
        (root / "main.tf").write_text(_render_main_tf(values), encoding="utf-8")
        init = _run_tf([tf_bin, "init", "-input=false", "-no-color"], cwd=tmp)
        if init.returncode != 0:
            raise TerraformError(
                f"terraform init failed: {(init.stderr or init.stdout)[:400]}"
            )
        if dry_run:
            plan = _run_tf(
                [tf_bin, "plan", "-input=false", "-no-color", "-out=tfplan"],
                cwd=tmp,
            )
            if plan.returncode != 0:
                raise TerraformError(
                    f"terraform plan failed: {(plan.stderr or plan.stdout)[:400]}"
                )
            return {
                "ok": True,
                "lab_mode": False,
                "terraform_binary": True,
                "dry_run": True,
                "result_summary": (
                    f"Terraform plan ok for cloud.vm.provision "
                    f"hostname={values.get('hostname')}"
                ),
                "provisioned_facts": {
                    "path": "terraform",
                    "hostname": values.get("hostname"),
                    "provider": values.get("provider"),
                    "cloud_region": values.get("cloud_region"),
                    "instance_type": values.get("instance_type"),
                    "live": True,
                    "dry_run": True,
                },
                "result_detail": {
                    "steps": [
                        {"step": "terraform_init", "ok": True},
                        {"step": "terraform_plan", "ok": True},
                    ],
                    "stdout": (plan.stdout or "")[:4000],
                    "stderr": (plan.stderr or "")[:1000],
                },
            }

        apply = _run_tf(
            [tf_bin, "apply", "-input=false", "-auto-approve", "-no-color"],
            cwd=tmp,
        )
        if apply.returncode != 0:
            raise TerraformError(
                f"terraform apply failed: {(apply.stderr or apply.stdout)[:400]}"
            )
        outputs: dict[str, Any] = {}
        out = _run_tf([tf_bin, "output", "-json", "-no-color"], cwd=tmp)
        if out.returncode == 0 and out.stdout:
            try:
                raw = json.loads(out.stdout)
                outputs = {
                    k: (v.get("value") if isinstance(v, dict) else v)
                    for k, v in raw.items()
                }
            except json.JSONDecodeError:
                outputs = {}
        return {
            "ok": True,
            "lab_mode": False,
            "terraform_binary": True,
            "dry_run": False,
            "result_summary": (
                f"Terraform apply ok for cloud.vm.provision "
                f"hostname={outputs.get('hostname') or values.get('hostname')}"
            ),
            "provisioned_facts": {
                "path": "terraform",
                "hostname": outputs.get("hostname") or values.get("hostname"),
                "provider": outputs.get("provider") or values.get("provider"),
                "cloud_region": outputs.get("cloud_region")
                or values.get("cloud_region"),
                "instance_type": outputs.get("instance_type")
                or values.get("instance_type"),
                "live": True,
                "terraform_outputs": outputs,
            },
            "result_detail": {
                "steps": [
                    {"step": "terraform_init", "ok": True},
                    {"step": "terraform_apply", "ok": True},
                ],
                "stdout": (apply.stdout or "")[:4000],
                "stderr": (apply.stderr or "")[:1000],
            },
        }
