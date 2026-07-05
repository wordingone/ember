#!/usr/bin/env bash
# Selftests for repo-guard hashed-denylist implementation
# Simple proof: (1) guard detects operator names with hashed denylist,
# (2) guard still works with plaintext denylist, (3) no denylist skips check

# Get the repo root by finding .git directory
GUARD_REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TESTS_PASS=0
TESTS_FAIL=0

test_pass() {
  printf '  PASS: %s\n' "$1"
  ((TESTS_PASS++))
}

test_fail() {
  printf '  FAIL: %s\n' "$1"
  ((TESTS_FAIL++))
}

echo "Testing hashed-denylist guard implementation..."
echo

# TEST 1: Create a sandbox repo with hashed denylist and a violation
echo "[TEST 1] Hashed denylist detects operator names"
TESTDIR1="$(mktemp -d)"
trap "rm -rf '$TESTDIR1'" EXIT
cd "$TESTDIR1"
git init -q .
git config user.name "Test"
git config user.email "test@test.com"

mkdir -p tools
cp "$GUARD_REPO/tools/repo-guard.sh" tools/
chmod +x tools/repo-guard.sh

# Create hashed denylist
cat > tools/.repo-guard-denylist.sha256 << 'EOF'
# Hashed denylist (one sha256 per lowercase name)
94f1d882f96d0714e1da520da3d22f0c8a9c08a0b6d543f744b6520f1e8c2ea4  wordingone
EOF

# Create required GOAL.md and a file WITH the violation
echo "# Goal" > GOAL.md
echo "repo owner: wordingone" > README.md
git add tools/.repo-guard-denylist.sha256 GOAL.md README.md
git commit -q -m "test with violation"

if ! bash tools/repo-guard.sh >/dev/null 2>&1; then
  test_pass "hashed-denylist correctly FAILS when wordingone is present"
else
  test_fail "hashed-denylist should FAIL but passed"
fi

# TEST 2: Clean the violation and guard should PASS
echo
echo "[TEST 2] Hashed denylist passes when clean"
cd "$TESTDIR1"
echo "repo owner: nobody" > README.md
git add README.md
git commit -q --amend -m "clean version"

if bash tools/repo-guard.sh >/dev/null 2>&1; then
  test_pass "hashed-denylist correctly PASSES when clean"
else
  test_fail "hashed-denylist should PASS but failed"
fi

# TEST 3: Plaintext denylist still works
echo
echo "[TEST 3] Plaintext denylist mode still works"
TESTDIR2="$(mktemp -d)"
cd "$TESTDIR2"
git init -q .
git config user.name "Test"
git config user.email "test@test.com"

mkdir -p tools
cp "$GUARD_REPO/tools/repo-guard.sh" tools/
chmod +x tools/repo-guard.sh

# Create plaintext denylist
cat > tools/.repo-guard-denylist << 'EOF'
testoperator
EOF

# Create required GOAL.md and a file with the violation
echo "# Goal" > GOAL.md
echo "author: testoperator" > README.md
git add tools/.repo-guard-denylist GOAL.md README.md
git commit -q -m "test with plaintext violation"

if ! bash tools/repo-guard.sh >/dev/null 2>&1; then
  test_pass "plaintext-denylist correctly FAILS when testoperator is present"
else
  test_fail "plaintext-denylist should FAIL but passed"
fi

# TEST 4: No denylist should skip the check (structural checks still run)
echo
echo "[TEST 4] No denylist skips names check"
TESTDIR3="$(mktemp -d)"
cd "$TESTDIR3"
git init -q .
git config user.name "Test"
git config user.email "test@test.com"

mkdir -p tools
cp "$GUARD_REPO/tools/repo-guard.sh" tools/
chmod +x tools/repo-guard.sh

# Create required GOAL.md and a file with a name but no denylist
echo "# Goal" > GOAL.md
echo "author: wordingone" > README.md
git add GOAL.md README.md
git commit -q -m "test without denylist"

if bash tools/repo-guard.sh >/dev/null 2>&1; then
  test_pass "no-denylist correctly PASSES (skips names check)"
else
  test_fail "no-denylist should PASS but failed"
fi

# SUMMARY
echo
echo "========================================"
printf 'Results: %d PASS, %d FAIL\n' "$TESTS_PASS" "$TESTS_FAIL"

if [ "$TESTS_FAIL" -gt 0 ]; then
  exit 1
fi
