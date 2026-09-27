"""Validate a complete Trivy report and block fixable HIGH/CRITICAL findings."""
import json
from pathlib import Path
import sys


def check(report):
    if report.get("SchemaVersion") != 2:
        raise ValueError("Missing or unsupported Trivy report schema")
    os_info = report.get("Metadata", {}).get("OS", {})
    if os_info.get("Family") != "debian" or not os_info.get("Name"):
        raise ValueError("Debian package scan was not identified")
    if os_info.get("EOSL") is True:
        raise ValueError("Base distribution is past its support period")
    results = report.get("Results")
    if not isinstance(results, list) or not any(r.get("Class") == "os-pkgs" for r in results):
        raise ValueError("Missing OS package results")
    total = fixed = 0
    for result in results:
        vulns = result.get("Vulnerabilities") or []
        if not isinstance(vulns, list):
            raise ValueError("Invalid vulnerability list")
        for vuln in vulns:
            if not isinstance(vuln, dict) or not isinstance(vuln.get("Severity"), str):
                raise ValueError("Invalid vulnerability entry")
            if vuln["Severity"] in {"HIGH", "CRITICAL"}:
                total += 1
                version = vuln.get("FixedVersion") or ""
                if not isinstance(version, str):
                    raise ValueError("Invalid fixed version")
                fixed += bool(version.strip())
    return total, fixed


if __name__ == "__main__":
    try:
        high, fixable = check(json.loads(Path(sys.argv[1]).read_text()))
        print(f"HIGH/CRITICAL: {high}; fixable: {fixable}; without published fix: {high - fixable}")
        sys.exit(42 if fixable else 0)
    except (OSError, ValueError, TypeError, AttributeError, IndexError) as exc:
        print(f"Invalid/incomplete scan report: {exc}", file=sys.stderr)
        sys.exit(1)
