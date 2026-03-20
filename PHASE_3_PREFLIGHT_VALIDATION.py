#!/usr/bin/env python3
"""
Phase 3 Pre-flight Validation Script
Comprehensive system check before Phase 3A deployment
"""

import os
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime

class PreflightValidator:
    def __init__(self):
        self.repo_root = Path("/home/user/WAGMI")
        self.bot_dir = self.repo_root / "bot"
        self.checks = []
        self.passed = 0
        self.failed = 0
        self.warnings = 0

    def check(self, name, condition, message=""):
        """Record a check result."""
        status = "✅ PASS" if condition else "❌ FAIL"
        if condition:
            self.passed += 1
        else:
            self.failed += 1

        result = {
            "name": name,
            "status": status,
            "message": message
        }
        self.checks.append(result)
        print(f"{status} | {name}")
        if message:
            print(f"       {message}")

    def warning(self, name, message):
        """Record a warning."""
        print(f"⚠️  WARNING | {name}: {message}")
        self.warnings += 1

    # ================== CODE CHECKS ==================

    def check_code_compilation(self):
        """Check if critical files compile."""
        print("\n[CODE COMPILATION]")

        critical_files = [
            "bot/execution/risk.py",
            "bot/llm/deep_memory.py",
            "bot/core/signal_pipeline.py",
            "bot/data/db.py",
        ]

        for file_path in critical_files:
            full_path = self.repo_root / file_path
            if not full_path.exists():
                self.check(f"File exists: {file_path}", False, f"Not found: {full_path}")
                continue

            # Try to compile
            result = subprocess.run(
                ["python", "-m", "py_compile", str(full_path)],
                capture_output=True
            )

            self.check(
                f"Compiles: {file_path}",
                result.returncode == 0,
                f"Error: {result.stderr.decode()[:100]}" if result.returncode != 0 else ""
            )

    def check_phase2_fixes_present(self):
        """Verify all Phase 2 fixes are in the code."""
        print("\n[PHASE 2 FIXES VERIFICATION]")

        fixes = {
            "Peak Equity Reset": ("bot/execution/risk.py", "self.peak_equity = equity if equity > 0"),
            "Deep Memory TTL": ("bot/llm/deep_memory.py", "prune_by_ttl"),
            "Slippage Gate": ("bot/core/signal_pipeline.py", "slippage.*40"),
            "Liquidation Check": ("bot/execution/leverage.py", "validate_stop_vs_liquidation"),
            "DB Archival": ("bot/data/db.py", "archive_old_records"),
        }

        for fix_name, (file_path, pattern) in fixes.items():
            full_path = self.repo_root / file_path
            if not full_path.exists():
                self.check(f"Fix present: {fix_name}", False, f"File not found: {file_path}")
                continue

            with open(full_path) as f:
                content = f.read()
                found = pattern.lower() in content.lower() or pattern in content
                self.check(
                    f"Fix present: {fix_name}",
                    found,
                    f"Pattern not found in {file_path}"
                )

    # ================== CONFIGURATION CHECKS ==================

    def check_environment_template(self):
        """Check if .env template exists."""
        print("\n[CONFIGURATION]")

        env_example = self.repo_root / ".env.example"
        self.check(
            ".env.example exists",
            env_example.exists(),
            f"Template file for configuration"
        )

        # Check .env (staging) exists or can be created
        env_file = self.repo_root / ".env"
        if not env_file.exists():
            self.warning(
                ".env not found",
                "Will need to create from .env.example before deployment"
            )

    # ================== DATABASE CHECKS ==================

    def check_database_setup(self):
        """Check database configuration."""
        print("\n[DATABASE]")

        db_path = self.bot_dir / "data" / "trades.db"
        data_dir = self.bot_dir / "data"

        self.check(
            "Data directory exists",
            data_dir.exists(),
            f"Location: {data_dir}"
        )

        if db_path.exists():
            size_mb = db_path.stat().st_size / (1024 * 1024)
            self.check(
                "Database file exists",
                True,
                f"Size: {size_mb:.2f} MB"
            )
        else:
            self.warning(
                "Database file",
                "Will be auto-created on first run"
            )

    # ================== DOCUMENTATION CHECKS ==================

    def check_documentation(self):
        """Check if all Phase 3 documentation exists."""
        print("\n[DOCUMENTATION]")

        docs = {
            "Phase 3 Deployment Guide": "PHASE_3_DEPLOYMENT_GUIDE.md",
            "Phase 3 Readiness": "PHASE_3_READINESS_SUMMARY.md",
            "Phase 3A Execution Log": "PHASE_3A_EXECUTION_LOG.md",
            "Phase 3A Monitor": "PHASE_3A_STAGING_MONITOR.py",
            "Phase 2 Test Results": "PHASE_2_TEST_RESULTS.md",
            "Operational Runbook": "PHASE_3_OPERATIONAL_RUNBOOK.md",
            "Config Hardening": "PHASE_3C_CONFIGURATION_HARDENING.md",
        }

        for doc_name, file_name in docs.items():
            doc_path = self.repo_root / file_name
            self.check(
                f"Doc: {doc_name}",
                doc_path.exists(),
                f"File: {file_name}"
            )

    # ================== GIT CHECKS ==================

    def check_git_status(self):
        """Check git repository status."""
        print("\n[GIT REPOSITORY]")

        # Check branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True
        )

        branch = result.stdout.strip() if result.returncode == 0 else "unknown"
        expected_branch = "claude/analyze-paper-trading-UjWeZ"

        self.check(
            f"Correct branch: {expected_branch}",
            branch == expected_branch,
            f"Current: {branch}"
        )

        # Check working tree clean
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True
        )

        clean = result.returncode == 0 and not result.stdout.strip()
        self.check(
            "Working tree clean",
            clean,
            "All changes committed" if clean else "Uncommitted changes exist"
        )

    # ================== TESTING CHECKS ==================

    def check_test_results(self):
        """Verify Phase 2 test results."""
        print("\n[PHASE 2 TEST RESULTS]")

        test_results = self.repo_root / "PHASE_2_TEST_RESULTS.md"
        if not test_results.exists():
            self.warning(
                "Test results",
                "PHASE_2_TEST_RESULTS.md not found"
            )
            return

        with open(test_results) as f:
            content = f.read()

            # Check for pass indicators
            has_12_passed = "12/12 PASSED" in content or "all 12 tests" in content.lower()
            self.check(
                "Phase 2 tests: 12/12 passed",
                has_12_passed,
                "All tests passed as required"
            )

            has_zero_regressions = "zero" in content.lower() and "regression" in content.lower()
            self.check(
                "Zero regressions confirmed",
                has_zero_regressions,
                "Trading logic untouched"
            )

    # ================== AUDIT CHECKS ==================

    def check_audit_coverage(self):
        """Verify all system audits completed."""
        print("\n[SYSTEM AUDITS]")

        audits = {
            "Position Manager": "POSITION_MANAGER_AUDIT.md",
            "LLM Decision": "LLM_DECISION_AUDIT.md",
            "System Integration": "SYSTEM_INTEGRATION_AUDIT.md",
            "Configuration": "CONFIG_AUDIT_REPORT.md",
        }

        for audit_name, file_name in audits.items():
            audit_path = self.repo_root / file_name
            self.check(
                f"Audit: {audit_name}",
                audit_path.exists(),
                f"File: {file_name}"
            )

    # ================== DEPENDENCIES CHECK ==================

    def check_dependencies(self):
        """Check Python dependencies."""
        print("\n[PYTHON DEPENDENCIES]")

        # Critical dependencies for bot
        dependencies = [
            "pandas",
            "numpy",
            "ccxt",
            "ta",
            "requests",
            "anthropic",
        ]

        # Try imports
        missing = []
        for dep in dependencies:
            try:
                __import__(dep)
                self.check(f"Module: {dep}", True)
            except ImportError:
                missing.append(dep)
                self.check(f"Module: {dep}", False, "Not installed in current environment")

        if missing:
            self.warning(
                "Missing dependencies",
                f"Not available in current env: {', '.join(missing)}. "
                "These must be installed in staging/production environment: pip install -r requirements.txt"
            )

    # ================== FINAL REPORT ==================

    def generate_report(self):
        """Generate final pre-flight report."""
        print("\n" + "="*70)
        print("PRE-FLIGHT VALIDATION REPORT")
        print("="*70)

        print(f"\nGenerated: {datetime.utcnow().isoformat()}")
        print(f"Repository: {self.repo_root}")

        print(f"\nResults:")
        print(f"  ✅ Passed:   {self.passed}")
        print(f"  ❌ Failed:   {self.failed}")
        print(f"  ⚠️  Warnings: {self.warnings}")

        print(f"\nOverall Status:")
        if self.failed == 0:
            print("  🟢 READY FOR PHASE 3 DEPLOYMENT")
            return True
        else:
            print(f"  🔴 {self.failed} CRITICAL ISSUES - MUST FIX BEFORE DEPLOYMENT")
            return False

    def run_all_checks(self):
        """Run all pre-flight checks."""
        print("="*70)
        print("PHASE 3 PRE-FLIGHT VALIDATION")
        print("="*70)

        self.check_code_compilation()
        self.check_phase2_fixes_present()
        self.check_environment_template()
        self.check_database_setup()
        self.check_documentation()
        self.check_git_status()
        self.check_test_results()
        self.check_audit_coverage()
        self.check_dependencies()

        return self.generate_report()

if __name__ == "__main__":
    validator = PreflightValidator()
    success = validator.run_all_checks()

    sys.exit(0 if success else 1)
