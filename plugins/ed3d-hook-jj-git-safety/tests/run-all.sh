#!/bin/sh
# run-all.sh -- execute the offline jj-git-safety verification suite.
#
# Usage:  ./run-all.sh            (exit 0 if all pass, 1 otherwise)
#         sh run-all.sh
set -u

dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
rc=0

for t in test-scope.sh test-package-layout.sh test-jj-preflight.sh; do
    echo
    echo "===== $t ====="
    if sh "$dir/$t"; then
        echo "==> $t PASS"
    else
        echo "==> $t FAIL"
        rc=1
    fi
done

echo
if [ "$rc" -eq 0 ]; then
    echo "ALL SUITES PASS"
else
    echo "ONE OR MORE SUITES FAILED"
fi
exit $rc
