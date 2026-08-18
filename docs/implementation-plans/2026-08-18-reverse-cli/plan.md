# Reverse CLI — Implementation Plan

## Goal
Build a minimal Java CLI tool that accepts a string and prints its reversed version. Deliver a runnable jar and a test suite verifying correctness for ASCII, whitespace, and multi-codepoint/unicode inputs.

## Implementation Summary
Use Maven (Java 17+) to create a tiny project named `reverse-cli`. Provide a Main class that reads CLI arguments and joins all args with a single space (exact behavior: join with ' '), then prints the reversed string using a code-point-aware reversal method. No external runtime dependencies required; tests use JUnit 5. Document the multi-arg behavior in README and include tests covering multi-arg usage.

## Implementation Plan
Phase A — Scaffolding (one commit per item):
- Create project root: `reverse-cli/`
- Files to create:
  - reverse-cli/pom.xml
  - reverse-cli/src/main/java/com/example/reverse/Main.java
  - reverse-cli/src/main/java/com/example/reverse/StringReverser.java
  - reverse-cli/src/test/java/com/example/reverse/StringReverserTest.java
  - reverse-cli/src/test/java/com/example/reverse/IntegrationCliIT.java (required — ProcessBuilder integration test that verifies exit code and stderr usage message; run during Maven verify phase using maven-failsafe-plugin)
Phase B — Tests & CI:
- Add JUnit 5 test class with cases for empty, whitespace, ascii, emoji/multibyte, and large-string smoke test.
Phase C — Packaging:
- Configure pom.xml with explicit coordinates and maven-shade-plugin to produce an executable fat JAR at `reverse-cli/target/reverse-cli-1.0-SNAPSHOT.jar`.

  Minimal required POM fields (implementor must use these exact values):
  - groupId: com.example
  - artifactId: reverse-cli
  - version: 1.0-SNAPSHOT
  - maven.compiler.source / target: 17

  Example: include maven-shade-plugin with a ManifestResourceTransformer setting `Main-Class: com.example.reverse.Main` so the produced JAR path is deterministic: `reverse-cli/target/reverse-cli-1.0-SNAPSHOT.jar`.

  Integration testing note (important): the integration test that exercises the packaged JAR must run after the package phase. Configure the Maven Failsafe Plugin and name the integration test to match the failsafe pattern (for example `*IT.java`, e.g. `IntegrationCliIT.java`). Example pom snippet to include in reverse-cli/pom.xml (add inside <build><plugins>):

  <plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-failsafe-plugin</artifactId>
    <version>3.1.2</version>
    <executions>
      <execution>
        <goals>
          <goal>integration-test</goal>
          <goal>verify</goal>
        </goals>
      </execution>
    </executions>
  </plugin>

  This ensures the packaged jar exists when the integration test runs and enables AC.5 to be verified by `mvn verify`.
Phase D — Verify & document:
- Run `mvn -q clean package` and `java -jar target/reverse-cli-1.0-SNAPSHOT.jar "hello"` locally. Add README with usage snippet and an executable `verify.sh` that runs the acceptance checks for AC.1..AC.5.

README examples to include (literal lines to copy):

Usage:
```
# Single-arg (quoted) – preserves spaces
java -jar target/reverse-cli-1.0-SNAPSHOT.jar "hello world"
# Output: dlrow olleh

# Multi-arg (equivalent behavior) – args are joined with a single space
java -jar target/reverse-cli-1.0-SNAPSHOT.jar hello world
# Output: dlrow olleh

# No-arg prints usage to stderr and exits non-zero
java -jar target/reverse-cli-1.0-SNAPSHOT.jar
# stderr: Usage: java -jar reverse-cli.jar <string>
```

Concrete file targets (relative to repo root):
- reverse-cli/pom.xml
- reverse-cli/mvnw and reverse-cli/.mvn/ (Maven Wrapper files)
- reverse-cli/src/main/java/com/example/reverse/Main.java
- reverse-cli/src/main/java/com/example/reverse/StringReverser.java
- reverse-cli/src/test/java/com/example/reverse/StringReverserTest.java
- reverse-cli/src/test/java/com/example/reverse/IntegrationCliIT.java
- reverse-cli/README.md
- docs/implementation-plans/2026-08-18-reverse-cli/verify.sh
- .github/workflows/maven.yml (optional but recommended)
## Acceptance Criteria
AC.1: The unit test suite passes. Verify: `cd reverse-cli && mvn -q test` exits 0. (Named test: StringReverserTest)
AC.2: The project packages to an executable jar with fixed coordinates. Verify:
- `cd reverse-cli && mvn -q -DskipTests package` produces `reverse-cli/target/reverse-cli-1.0-SNAPSHOT.jar` (pom must use groupId=com.example, artifactId=reverse-cli, version=1.0-SNAPSHOT and shade plugin configured as specified).
AC.3: The jar when run with `java -jar target/reverse-cli-1.0-SNAPSHOT.jar "hello"` prints `olleh` to stdout. (Verify with shell command and exit code 0.)
AC.4: Unicode/multibyte handling preserved (emoji and surrogate pairs). Verify: unit test `StringReverserTest::reverse_unicode_multibyte_characters` passes.
AC.5: CLI usage message appears and exit code non-zero when run without arguments. Verify: Integration test `IntegrationCliIT::noArgsPrintsUsageAndExitsNonZero` (reverse-cli/src/test/java/com/example/reverse/IntegrationCliIT.java) runs the packaged jar with ProcessBuilder during the Maven verify phase (maven-failsafe-plugin), asserts the process exit code != 0 and that stderr contains a case-insensitive 'usage' token. Verification command: `cd reverse-cli && ./mvnw -q verify` (or `mvn -q verify` if no wrapper).

## Test Strategy
- Unit tests (JUnit 5) in `src/test/java`: cover null/empty, ascii, whitespace, unicode/emoji, combining marks, large input.
- Integration tests: add a required ProcessBuilder-based integration test `IntegrationCliIT` that runs the packaged jar during the Maven verify phase (maven-failsafe-plugin) and verifies exit codes and stderr usage messages (used for AC.5). Keep a fast unit-level Main.main System.out capture test for quick checks but do not rely on it for process-level behaviors.
- Commands (standardized):
  - Unit tests: `cd reverse-cli && ./mvnw -q test` (or `mvn -q test`) — verifies AC.1 and AC.4
  - Packaging (skip tests): `cd reverse-cli && ./mvnw -q -DskipTests package` (or `mvn -q -DskipTests package`) — produces the jar for AC.2
  - Full verification (tests + integration tests): `cd reverse-cli && ./mvnw -q verify` (or `mvn -q verify`) — runs the failsafe integration tests and verifies AC.5
  - Quick local run of the packaged jar (sanity): `cd reverse-cli && java -jar target/reverse-cli-1.0-SNAPSHOT.jar "hello"` — verifies AC.3
- CI recommendation: add a Maven Wrapper (mvnw) and a simple GitHub Actions workflow at `.github/workflows/maven.yml` to run tests and package on JDK 17. Include the wrapper in the scaffold.

## Review Strategy
- Plan-review gate: use `plan-reviewer` (kimi-k3) to check plan completeness.
- Execution: one builder (task-implementor-fast) will implement the scaffold and tests, commit each logical step, and return full agent responses including commit SHAs.
- Code review: adversarial-review will run after `base_sha`/`head_sha` are recorded.

## Risks
- Quoting and shell handling: user must quote strings with spaces; plan documents this in README.
- Unicode normalization: tests assert expected code-point reversal; if normalization required, add Normalizer step.
- Java version mismatch: target Java 17; confirm environment or add maven toolchain if necessary.

---

Plan created: 2026-08-18
