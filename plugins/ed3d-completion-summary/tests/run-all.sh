#!/bin/sh
# run-all.sh -- execute the offline ed3d-completion-summary verification suite.
#
# Usage:  ./run-all.sh            (exit 0 if all pass, 1 otherwise)
#         sh run-all.sh
set -u

dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
rc=0

for t in test-completion-reminder.sh test-package-layout.sh; do
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
