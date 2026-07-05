# [PATH-REWRITE 2026-07-01] Imported from B:/M/avir/leo/state/ember-totality-build/
# into B:/M/ember-goalforge/scripts/ember_totality/. The hardcoded absolute read
# of test_c9.py at /mnt/b/M/avir/leo/state/ember-totality-build/test_c9.py was
# replaced with a script-relative path (HEREDIR, derived from $0) so this probe
# resolves under the new repo root instead of the old avir/leo tree. No test
# logic changed.
set -e
HEREDIR="$(cd "$(dirname "$0")" && pwd)"
TMP=$(mktemp -d)
echo "TMP=$TMP"

mkvariant() {
  ROOT="$1" OUT="$2" SRC="$HEREDIR/test_c9.py" python3 <<'PYEOF'
import os, re
root=os.environ["ROOT"]; out=os.environ["OUT"]; src=os.environ["SRC"]
s=open(src,encoding="utf-8").read()
s=re.sub(r"_CANDIDATE_ROOTS = \[.*?\]", "_CANDIDATE_ROOTS = [%r]"%root, s, flags=re.S)
open(out,"w",encoding="utf-8").write(s)
PYEOF
}

echo "===== TEST 1: empty receipts dir -> expect RED ====="
E="$TMP/empty"; mkdir -p "$E/receipts"
mkvariant "$E" "$TMP/t_empty.py"; python3 "$TMP/t_empty.py"; echo "exit=$?"

echo; echo "===== TEST 2: only docs-only window -> expect RED ====="
D="$TMP/donly"; mkdir -p "$D/receipts/x"
printf '%s' '{"receipt_type":"code_vs_docs_metric","metric":{"verdict":"docs_only_no_executable_delta","line_totals":{"code":0,"docs":500},"doc_lifecycle_totals":{"before_project":0,"during_project":0,"after_project":500},"code_vs_docs":{"code_fraction":0.0,"docs_fraction":1.0}}}' > "$D/receipts/x/r.json"
mkvariant "$D" "$TMP/t_donly.py"; python3 "$TMP/t_donly.py"; echo "exit=$?"

echo; echo "===== TEST 3: scaffold-violation marker -> expect RED ====="
S="$TMP/scaf"; mkdir -p "$S/receipts/x"
printf '%s' '{"receipt_type":"code_vs_docs_metric","note":"invalid_scaffold_before_core","metric":{"verdict":"mixed_code_and_docs","line_totals":{"code":900,"docs":100},"doc_lifecycle_totals":{"before_project":0,"during_project":50,"after_project":50},"code_vs_docs":{"code_fraction":0.9,"docs_fraction":0.1}}}' > "$S/receipts/x/r.json"
mkvariant "$S" "$TMP/t_scaf.py"; python3 "$TMP/t_scaf.py"; echo "exit=$?"

echo; echo "===== TEST 4: STUB empty-object json -> expect RED ====="
B="$TMP/stub"; mkdir -p "$B/receipts/x"
for i in 1 2 3; do printf '%s' '{}' > "$B/receipts/x/$i.json"; done
mkvariant "$B" "$TMP/t_stub.py"; python3 "$TMP/t_stub.py"; echo "exit=$?"

echo; echo "===== TEST 5: STUB hardcoded GREEN string in content -> expect RED ====="
H="$TMP/hard"; mkdir -p "$H/receipts/x"
printf '%s' '{"receipt_type":"note","text":"GREEN C9 CHK satisfied everything passes"}' > "$H/receipts/x/r.json"
mkvariant "$H" "$TMP/t_hard.py"; python3 "$TMP/t_hard.py"; echo "exit=$?"

echo; echo "===== TEST 6: incomplete metric (no doc_lifecycle) -> expect RED ====="
I="$TMP/incomp"; mkdir -p "$I/receipts/x"
printf '%s' '{"receipt_type":"code_vs_docs_metric","metric":{"verdict":"code_only_executable_delta","line_totals":{"code":900,"docs":10},"code_vs_docs":{"code_fraction":0.99,"docs_fraction":0.01}}}' > "$I/receipts/x/r.json"
mkvariant "$I" "$TMP/t_incomp.py"; python3 "$TMP/t_incomp.py"; echo "exit=$?"

echo; echo "===== TEST 7: valid code_only_executable_delta -> expect GREEN ====="
G="$TMP/good"; mkdir -p "$G/receipts/x"
printf '%s' '{"receipt_type":"code_vs_docs_metric","metric":{"verdict":"code_only_executable_delta","line_totals":{"code":900,"docs":10},"doc_lifecycle_totals":{"before_project":0,"during_project":5,"after_project":5},"code_vs_docs":{"code_fraction":0.99,"docs_fraction":0.01}}}' > "$G/receipts/x/r.json"
mkvariant "$G" "$TMP/t_good.py"; python3 "$TMP/t_good.py"; echo "exit=$?"

echo; echo "===== TEST 8: substrate verdict BUT code=0 -> expect RED ====="
Z="$TMP/zero"; mkdir -p "$Z/receipts/x"
printf '%s' '{"receipt_type":"code_vs_docs_metric","metric":{"verdict":"mixed_code_and_docs","line_totals":{"code":0,"docs":500},"doc_lifecycle_totals":{"before_project":0,"during_project":0,"after_project":500},"code_vs_docs":{"code_fraction":0.0,"docs_fraction":1.0}}}' > "$Z/receipts/x/r.json"
mkvariant "$Z" "$TMP/t_zero.py"; python3 "$TMP/t_zero.py"; echo "exit=$?"

rm -rf "$TMP"
