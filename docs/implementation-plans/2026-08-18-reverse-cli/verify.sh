#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.." || exit 1
cd reverse-cli
# Choose mvn command (prefer wrapper if present)
MVN=mvn
if [ -x ./mvnw ]; then
  MVN=./mvnw
fi
# Run unit tests
$MVN -q test
# Package the artifact (skip unit tests to speed up if desired)
$MVN -q -DskipTests package
JAR=target/reverse-cli-1.0-SNAPSHOT.jar
if [ ! -f "$JAR" ]; then
  echo "ERROR: expected jar $JAR not found" >&2
  exit 2
fi
# Verify POM coordinates
if ! grep -F "<groupId>com.example</groupId>" pom.xml >/dev/null; then
  echo "ERROR: pom.xml missing required groupId com.example" >&2
  exit 6
fi
if ! grep -F "<artifactId>reverse-cli</artifactId>" pom.xml >/dev/null; then
  echo "ERROR: pom.xml missing required artifactId reverse-cli" >&2
  exit 7
fi
if ! grep -F "<version>1.0-SNAPSHOT</version>" pom.xml >/dev/null; then
  echo "ERROR: pom.xml missing required version 1.0-SNAPSHOT" >&2
  exit 8
fi
# Verify MANIFEST Main-Class
if ! (unzip -p "$JAR" META-INF/MANIFEST.MF 2>/dev/null | grep -i "Main-Class: com.example.reverse.Main" >/dev/null); then
  echo "ERROR: JAR manifest missing Main-Class: com.example.reverse.Main" >&2
  unzip -l "$JAR" >&2 || true
  exit 9
fi
# Quick smoke run of packaged jar to verify output
OUT=$({ java -jar "$JAR" "hello" 2>&1 || true; })
if [[ "$OUT" != *"olleh"* ]]; then
  echo "ERROR: expected 'olleh' in stdout from packaged jar, got: $OUT" >&2
  exit 3
fi
# Run Maven verify to execute the failsafe integration test (IntegrationCliIT)
$MVN -q verify || {
  echo "ERROR: mvn verify failed (integration tests)" >&2
  exit 10
}

echo "All acceptance checks passed."