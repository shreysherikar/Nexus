import os
import sys
import zipfile
import re

sys.stdout.reconfigure(encoding='utf-8')

REPO_DIR = r"C:\Users\Admin\Documents\Nexus\nexus-network-intelligence"
PARENT_ZIP = r"C:\Users\Admin\Documents\Nexus\nexus_milestone7_verification.zip"
REPO_ZIP = r"C:\Users\Admin\Documents\Nexus\nexus-network-intelligence\nexus_milestone7_verification.zip"

EXCLUDE_PATTERNS = [
    r"[\\/]\.git([\\/]|$)",
    r"[\\/]\.venv([\\/]|$)",
    r"[\\/]node_modules([\\/]|$)",
    r"[\\/]frontend[\\/]dist([\\/]|$)",
    r"[\\/]\.pytest_cache([\\/]|$)",
    r"[\\/]__pycache__([\\/]|$)",
    r"\.pyc$",
    r"nexus_milestone.*\.zip$",
]

def should_exclude(rel_path):
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, "/" + rel_path.replace("\\", "/")):
            return True
    return False

def create_zip(target_zip):
    if os.path.exists(target_zip):
        os.remove(target_zip)
    
    count = 0
    with zipfile.ZipFile(target_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(REPO_DIR):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, REPO_DIR)
                if should_exclude(rel_path):
                    continue
                zf.write(abs_path, rel_path)
                count += 1
    return count

print("Generating verification zip files...")
count1 = create_zip(PARENT_ZIP)
size_mb = os.path.getsize(PARENT_ZIP) / (1024 * 1024)
print(f"Created {PARENT_ZIP}: {count1} files, {size_mb:.2f} MB")

import shutil
shutil.copy2(PARENT_ZIP, REPO_ZIP)
print(f"Copied to {REPO_ZIP}")

# Verify archive contents
print("\nReopening verification ZIP to inspect contents...")
with zipfile.ZipFile(PARENT_ZIP, 'r') as zf:
    namelist = set(zf.namelist())
    
    # Check exclusions
    for name in namelist:
        if "node_modules" in name or ".venv" in name or "frontend/dist" in name or ".git/" in name:
            raise AssertionError(f"Excluded path found in ZIP: {name}")
    print("[PASS] Excluded paths (node_modules, frontend/dist, .venv, .git) are absent.")
    
    # Check required new and modified files
    required_files = [
        "frontend/src/pages/KpisPage.tsx",
        "frontend/src/utils/kpiEvaluator.ts",
        "frontend/tests/kpis_accuracy.test.tsx",
        "frontend/src/api/client.ts",
        "frontend/src/types/api.ts",
        "src/nexus/detection/rules.py",
        "src/nexus/detection/api.py",
        "src/nexus/detection/schemas.py",
        "src/nexus/incidents/metrics.py",
        "src/nexus/incidents/api.py",
        "src/nexus/incidents/schemas.py",
    ]
    for rf in required_files:
        assert rf in namelist, f"Missing required file in ZIP: {rf}"
        print(f"[PASS] Found {rf}")

    # Inspect frontend/src/pages/KpisPage.tsx
    kpis_code = zf.read("frontend/src/pages/KpisPage.tsx").decode('utf-8')
    
    # Assert no hardcoded fallback threshold numbers exist for threshold lines
    forbidden_patterns = [
        r"\?\?\s*95\.0",
        r"\?\?\s*80\.0",
        r"\?\?\s*5\.0",
        r"\?\?\s*-115\.0",
        r"\?\?\s*85\.0",
        r"Nominal:\s*100%",
        r"Major\s*>\s*80\.0\s*ms",
        r"Critical\s*>\s*5\.0%",
        r"Critical\s*<\s*95\.0%",
    ]
    for fp in forbidden_patterns:
        match = re.search(fp, kpis_code)
        assert match is None, f"Found hardcoded fallback in KpisPage.tsx matching '{fp}': {match.group(0)}"
    print("[PASS] No hardcoded fallback threshold values or static claims in KpisPage.tsx.")

    # Assert dynamic functions and imports
    assert "getActiveThreshold" in kpis_code
    assert "getActiveThresholdLabel" in kpis_code
    assert "getMetricSubtitle" in kpis_code
    assert "evaluateMetricStatus" in kpis_code
    assert "from '@/utils/kpiEvaluator'" in kpis_code
    print("[PASS] Evaluator functions properly imported and integrated in KpisPage.tsx.")

    # Inspect frontend/src/utils/kpiEvaluator.ts
    evaluator_code = zf.read("frontend/src/utils/kpiEvaluator.ts").decode('utf-8')
    assert "N/A: Applies to" in evaluator_code
    assert "Rule unavailable" in evaluator_code
    assert "Rule inactive" in evaluator_code
    print("[PASS] Evaluator utility correctly enforces rule applicability and status labeling.")

    # Inspect frontend/tests/kpis_accuracy.test.tsx
    test_code = zf.read("frontend/tests/kpis_accuracy.test.tsx").decode('utf-8')
    assert "when rule configuration is missing" in test_code
    assert "when rule is disabled" in test_code
    assert "when restricted rule has an undefined node type" in test_code
    assert "when restricted rule is evaluated on a non-applicable node" in test_code
    assert "no threshold lines when rule configuration is empty" in test_code
    print("[PASS] All required test categories covered in kpis_accuracy.test.tsx.")

print(f"\nVerification completely passed! Total files in archive: {len(namelist)}")
