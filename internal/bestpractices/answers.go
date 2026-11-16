// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
)

// Answer is one criterion's proposed status (Met, Unmet, N/A or ?) and its
// justification.
type Answer struct {
	Criterion, Status, Why string
}

// Answers is a set of answers in the form's order.
type Answers []Answer

// Get returns the answer to criterion c.
func (a Answers) Get(c string) (Answer, bool) {
	for _, x := range a {
		if x.Criterion == c {
			return x, true
		}
	}
	return Answer{}, false
}

// Derive returns the answer to every passing criterion from the checkout at
// repoDir. slug is OWNER/NAME (default: the origin remote, else
// swarm-routing/<directory name>); today is YYYY-MM-DD (default: today).
func Derive(repoDir, slug, today string) (Answers, error) {
	if slug == "" {
		slug = gitSlug(repoDir)
	}
	if slug == "" {
		slug = Org + "/" + absBase(repoDir)
	}
	if today == "" {
		today = time.Now().Format("2006-01-02")
	}
	r, err := newRepo(repoDir, slug)
	if err != nil {
		return nil, err
	}
	a := map[string]Answer{}
	put := func(c, status, why string) { a[c] = Answer{c, status, why} }
	unknown := func(c, why string) { put(c, "?", why) }
	or := func(xs ...string) string {
		for _, x := range xs {
			if x != "" {
				return x
			}
		}
		return ""
	}

	issues := r.base + "/issues"
	readme := r.has("README.md", "README.rst", "README")
	contributing := r.has("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md")
	contribURL := r.orgFile("CONTRIBUTING.md")
	if contributing != "" {
		contribURL = r.url(contributing)
	}
	security := r.has("SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md")
	securityURL := r.orgFile("SECURITY.md")
	if security != "" {
		securityURL = r.url(security)
	}
	securityText := r.text(security)

	// basics
	if readme != "" {
		put("description_good", "Met", r.url(readme)+" describes what the software does.")
		put("documentation_basics", "Met", "Basic documentation: "+r.url(readme)+".")
	} else {
		unknown("description_good", "No README.")
		unknown("documentation_basics", "No README.")
	}
	if readme != "" && contribURL != "" {
		put("interact", "Met", fmt.Sprintf("Obtain: %s; feedback: %s; contribute: %s.", r.url(readme), issues, contribURL))
		put("contribution", "Met", "The contribution process: "+contribURL+".")
		put("contribution_requirements", "Met",
			"Requirements for acceptable contributions (style, Conventional Commit titles, "+
				"tests, licence headers): "+contribURL+".")
	} else {
		for _, c := range []string{"interact", "contribution", "contribution_requirements"} {
			unknown(c, "No CONTRIBUTING file.")
		}
	}
	var licFiles []string
	for _, f := range []string{"LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "LICENSE-MIT"} {
		if r.files[f] {
			licFiles = append(licFiles, f)
		}
	}
	spdxSet := map[string]bool{}
	for _, f := range licFiles {
		for _, l := range licences {
			if l.rx.MatchString(r.text(f)) {
				spdxSet[l.spdx] = true
			}
		}
	}
	var spdx []string
	for s := range spdxSet {
		spdx = append(spdx, s)
	}
	sort.Strings(spdx)
	urls := func(fs []string) string {
		out := make([]string, len(fs))
		for i, f := range fs {
			out[i] = r.url(f)
		}
		return strings.Join(out, ", ")
	}
	if len(licFiles) > 0 {
		where := append([]string{}, licFiles...)
		if r.has("LICENSING.md") != "" {
			where = append(where, "LICENSING.md")
		}
		put("license_location", "Met", "The licence is in "+urls(where)+".")
	} else {
		unknown("license_location", "No LICENSE file.")
	}
	if len(spdx) > 0 {
		why := fmt.Sprintf("%s (%s), approved by the OSI.", strings.Join(spdx, " and "), urls(licFiles))
		put("floss_license", "Met", why)
		put("floss_license_osi", "Met", why)
	} else {
		unknown("floss_license", "No licence text recognised.")
		unknown("floss_license_osi", "No licence text recognised.")
	}
	docs := r.has("docs/")
	if docs == "" {
		for _, f := range r.sorted {
			if strings.HasPrefix(f, "docs/") {
				docs = f
				break
			}
		}
	}
	api := r.has("Doxyfile", "api/Doxyfile", "docs/Doxyfile", "mkdocs.yml")
	if docs != "" || api != "" {
		target := r.url(api)
		if docs != "" {
			target = r.url("docs/")
		}
		put("documentation_interface", "Met", "The external interface is documented: "+target+".")
	} else {
		unknown("documentation_interface", "No docs/ or API reference found.")
	}
	put("sites_https", "Met",
		"The project site, repository and releases are GitHub's, served over HTTPS only: "+r.base+".")
	put("discussion", "Met", "GitHub issues and pull requests: searchable, linkable, open: "+issues+".")
	docURL := r.base
	if readme != "" {
		docURL = r.url(readme)
	}
	put("english", "Met", "Documentation ("+docURL+"), issues and code comments are in English.")
	last := lastCommit(repoDir)
	if maintained(last, today) {
		put("maintained", "Met", "Last commit to main "+last+": "+r.base+"/commits/main.")
	} else {
		unknown("maintained", "The last commit is not known or is over a year old.")
	}

	// change control
	put("repo_public", "Met", "Public git repository: "+r.base+".")
	put("repo_track", "Met", "git records each change, its author and date: "+r.base+"/commits/main.")
	put("repo_interim", "Met", "Every change is a pull request to main, public before a release: "+r.base+"/pulls.")
	put("repo_distributed", "Met", "git, a distributed version control system: "+r.base+".")
	cz := r.has(".cz.toml", "VERSION")
	changelog := r.has("CHANGELOG.md", "CHANGELOG", "NEWS.md")
	clText := r.text(changelog)
	semver := regexp.MustCompile(`(?m)^#+ \[?v?\d+\.\d+\.\d+`).MatchString(clText)
	if cz != "" || semver {
		ev := r.url(changelog)
		if cz != "" {
			ev = r.url(cz)
		}
		put("version_unique", "Met", "Each release has a unique version: "+ev+".")
		put("version_semver", "Met", "Semantic Versioning, bumped by Commitizen: "+ev+".")
		put("version_tags", "Met", "Each release is a git tag vX.Y.Z: "+r.base+"/tags.")
	} else {
		for _, c := range []string{"version_unique", "version_semver", "version_tags"} {
			unknown(c, "No release version found (.cz.toml, VERSION or CHANGELOG headings).")
		}
	}
	if changelog != "" {
		put("release_notes", "Met", "Release notes: "+r.url(changelog)+" and "+r.base+"/releases.")
		if regexp.MustCompile(`\b(CVE-\d{4}-\d+|GHSA-[0-9a-z-]+)`).MatchString(clText) {
			put("release_notes_vulns", "Met", "Fixed vulnerabilities are named in "+r.url(changelog)+".")
		} else {
			put("release_notes_vulns", "N/A",
				"No release fixed a publicly known vulnerability (no CVE or GHSA in "+r.url(changelog)+").")
		}
	} else {
		unknown("release_notes", "No CHANGELOG.")
		unknown("release_notes_vulns", "No CHANGELOG.")
	}

	// reporting
	put("report_process", "Met", "Bugs are reported in GitHub issues: "+issues+".")
	put("report_tracker", "Met", "GitHub issues: "+issues+".")
	put("report_archive", "Met", "Public, searchable archive of reports and responses: "+issues+"?q=.")
	if securityURL != "" {
		put("vulnerability_report_process", "Met", "The process for reporting vulnerabilities: "+securityURL+".")
	} else {
		unknown("vulnerability_report_process", "No SECURITY.md.")
	}
	if regexp.MustCompile(`(?i)private vulnerability report|security advisor|report a vulnerability`).MatchString(securityText) ||
		(security == "" && securityURL != "") {
		put("vulnerability_report_private", "Met",
			"Private reports through GitHub private vulnerability reporting: "+securityURL+", "+
				r.base+"/security/advisories/new.")
	} else {
		unknown("vulnerability_report_private", "SECURITY.md names no private channel.")
	}

	// quality
	build := r.has("Makefile", "CMakeLists.txt", "core/CMakeLists.txt", "pyproject.toml",
		"python/pyproject.toml", "docker/Dockerfile", "Dockerfile")
	tools := map[string]string{"Makefile": "make", "CMakeLists.txt": "CMake", "core/CMakeLists.txt": "CMake",
		"pyproject.toml": "pip", "python/pyproject.toml": "pip",
		"docker/Dockerfile": "Docker", "Dockerfile": "Docker"}
	var sources, cxx, cmakes []string
	for _, f := range r.sorted {
		if endsWith(f, ".c", ".cc", ".cpp", ".h", ".hpp", ".py", ".sh") {
			sources = append(sources, f)
		}
		if endsWith(f, ".c", ".cc", ".cpp", ".h", ".hpp") {
			cxx = append(cxx, f)
		}
		if strings.HasSuffix(f, "CMakeLists.txt") {
			cmakes = append(cmakes, f)
		}
	}
	if build != "" {
		put("build", "Met", fmt.Sprintf("Built with %s: %s.", tools[build], r.url(build)))
		put("build_common_tools", "Met", fmt.Sprintf("%s, a common build tool: %s.", tools[build], r.url(build)))
		put("build_floss_tools", "Met",
			fmt.Sprintf("Builds with FLOSS tools only (%s, GCC/Clang, Python): %s.", tools[build], r.url(build)))
	} else if len(sources) > 0 && len(cxx) == 0 { // interpreted only; compiled code without a build file stays ?
		for _, c := range []string{"build", "build_common_tools", "build_floss_tools"} {
			put(c, "N/A", "Scripts run as they are, with nothing to build: "+r.base+".")
		}
	} else {
		for _, c := range []string{"build", "build_common_tools", "build_floss_tools"} {
			unknown(c, "No build file.")
		}
	}
	testDir := regexp.MustCompile(`(^|/)tests?/`)
	testPy := regexp.MustCompile(`(^|/)test_[^/]+\.py$`)
	var tests []string
	for _, f := range r.sorted {
		if testDir.MatchString(f) || testPy.MatchString(f) {
			tests = append(tests, f)
		}
	}
	selfTest := r.workflowURL(`--self-test`)
	makeTest := regexp.MustCompile(`(?m)^test:`).MatchString(r.text(r.has("Makefile")))
	if len(tests) > 0 || selfTest != "" {
		where := selfTest
		if len(tests) > 0 {
			where = r.url(dirname(tests[0]) + "/")
		}
		put("test", "Met", "An automated test suite: "+where+".")
		how, at := "the commands in the CI workflow", where
		if makeTest {
			how, at = "`make test`", r.url("Makefile")
		}
		put("test_invocation", "Met", fmt.Sprintf("Run with %s: %s.", how, at))
	} else {
		unknown("test", "No test suite found.")
		unknown("test_invocation", "No test suite found.")
	}
	coverage := r.workflowURL(`codecov|gcovr|--coverage|coverage run|pytest-cov`)
	// measured is not "most": the owner reads the numbers and answers
	if coverage != "" {
		unknown("test_most", "The owner answers from the coverage report: "+coverage+".")
	} else {
		unknown("test_most", "No coverage report found.")
	}
	// Python's \bpull_request\b(?!_target): \b already fails before "_target"
	if ci := r.workflowURL(`\bpull_request\b`); ci != "" {
		put("test_continuous_integration", "Met", "GitHub Actions on every pull request: "+ci+".")
	} else {
		unknown("test_continuous_integration", "No workflow runs on pull requests.")
	}
	policy := ""
	for _, f := range []string{"CONTRIBUTING.md", ".github/CONTRIBUTING.md", "AGENTS.md"} {
		if r.files[f] && testPolicy.MatchString(r.text(f)) {
			policy = f
			break
		}
	}
	policyURL := ""
	if policy != "" {
		policyURL = r.url(policy)
	} else if contributing == "" && contribURL != "" {
		policyURL = contribURL
	}
	if policyURL != "" {
		put("test_policy", "Met", "New functionality needs tests: "+policyURL+".")
		// the policy is written; that recent changes followed it is history, the owner's call
		unknown("tests_are_added", "The owner confirms recent changes followed "+policyURL+".")
		put("tests_documented_added", "Met", "The test policy is in the contribution instructions: "+policyURL+".")
	} else {
		for _, c := range []string{"test_policy", "tests_are_added", "tests_documented_added"} {
			unknown(c, "No written test policy found.")
		}
	}
	cmakeTexts := make([]string, len(cmakes))
	for i, f := range cmakes {
		cmakeTexts[i] = r.text(f)
	}
	cmakeText := strings.Join(cmakeTexts, " ")
	strictCI := r.workflowURL(`--strict-warnings|-Werror`)
	ruff := r.workflowURL(`\bruff\b|reusable-python-ci`)
	wall := strings.Contains(cmakeText, "-Wall")
	switch {
	case len(cxx) > 0 && (wall || strictCI != ""):
		ev := strictCI
		if ev == "" {
			ev = r.url(cmakes[0])
		}
		put("warnings", "Met", "Compiler warnings on (-Wall -Wextra): "+ev+".")
		if strictCI != "" || regexp.MustCompile(`-Werror|COMPILE_WARNING_AS_ERROR`).MatchString(cmakeText) {
			put("warnings_fixed", "Met", "Warnings are errors in CI, so they are fixed before merge: "+ev+".")
			put("warnings_strict", "Met", "Strict warnings as errors: "+ev+".")
		} else {
			unknown("warnings_fixed", "Warnings are not errors.")
			unknown("warnings_strict", "Warnings are not errors.")
		}
	case len(cxx) == 0 && ruff != "":
		put("warnings", "Met", "The ruff linter on every pull request: "+ruff+".")
		put("warnings_fixed", "Met", "A ruff finding fails CI, so it is fixed before merge: "+ruff+".")
		put("warnings_strict", "Met", "ruff with an explicit rule set, findings as errors: "+ruff+".")
	default:
		for _, c := range []string{"warnings", "warnings_fixed", "warnings_strict"} {
			unknown(c, "No compiler warnings or linter found.")
		}
	}

	// security
	cryptoSrc := ""
	for _, f := range sources {
		if cryptoUse.MatchString(r.text(f)) {
			cryptoSrc = f
			break
		}
	}
	if v, ok := r.cfg["bestpractices_crypto"].(bool); (ok && v) || cryptoSrc != "" {
		for _, c := range Crypto {
			unknown(c, "The software uses cryptography: the owner answers.")
		}
	} else {
		for _, c := range Crypto {
			put(c, "N/A", "The software implements and calls no cryptography: "+r.base+".")
		}
	}
	put("delivery_mitm", "Met", "Delivered over HTTPS only (GitHub releases and git): "+r.base+"/releases.")
	if plain := r.grep(`(curl|wget)[^\n]*http://`, ".sh", ".yml", ".yaml", ".py", "Makefile"); plain != "" {
		unknown("delivery_unsigned", plain+" fetches over plain HTTP.")
	} else {
		put("delivery_unsigned", "Met",
			"No hash is retrieved over plain HTTP: releases and checksums come over HTTPS ("+r.base+"/releases).")
	}

	// analysis
	codeql := r.workflowURL(`codeql`)
	sonar := r.workflowURL(`sonar`)
	tidy := r.workflowURL(`clang-tidy`)
	sa := or(codeql, sonar, tidy, ruff)
	if sa != "" {
		put("static_analysis", "Met", "Static analysis on every change: "+sa+".")
		if codeql != "" || sonar != "" {
			name := "SonarQube Cloud"
			if codeql != "" {
				name = "CodeQL"
			}
			put("static_analysis_common_vulnerabilities", "Met",
				name+" looks for common vulnerabilities: "+or(codeql, sonar)+".")
		} else {
			unknown("static_analysis_common_vulnerabilities", "No vulnerability-oriented analyser.")
		}
		saText := ""
		for _, w := range r.workflows {
			if r.url(w.file) == sa {
				saText = w.text
				break
			}
		}
		if regexp.MustCompile(`\bpull_request\b|\bpush\b`).MatchString(saText) {
			put("static_analysis_often", "Met", "Runs on every pull request or push: "+sa+".")
		} else {
			unknown("static_analysis_often", "Static analysis is not run on each change.")
		}
	} else {
		for _, c := range []string{"static_analysis", "static_analysis_common_vulnerabilities", "static_analysis_often"} {
			unknown(c, "No static analysis found.")
		}
	}
	unknown("static_analysis_fixed", "The owner confirms medium and higher findings are fixed promptly.")
	fuzz := or(r.workflowURL(`fuzz`), r.grep(`-fsanitize=fuzzer|LLVMFuzzerTestOneInput`, ".txt", ".cmake", ".cc", ".cpp"))
	san := r.workflowURL(`sanitiz|-fsanitize`)
	if san == "" {
		if f := r.grep(`-fsanitize=address`, "CMakeLists.txt", ".cmake"); f != "" {
			san = r.url(f)
		}
	}
	if fuzz != "" && !strings.HasPrefix(fuzz, "https://") {
		fuzz = r.url(fuzz)
	}
	dyn := or(fuzz, san)
	if dyn != "" {
		kind := "sanitizers"
		if fuzz != "" {
			kind = "fuzzing"
		}
		put("dynamic_analysis", "Met", "Dynamic analysis ("+kind+") in CI: "+dyn+".")
		put("dynamic_analysis_fixed", "Met", "A sanitizer or fuzz failure fails CI and is fixed before merge: "+dyn+".")
	} else {
		unknown("dynamic_analysis", "No fuzzing or sanitizer runs found.")
		unknown("dynamic_analysis_fixed", "No dynamic analysis found.")
	}
	switch {
	case len(cxx) == 0:
		put("dynamic_analysis_unsafe", "N/A", "Written in memory-safe languages only (Python, shell): "+r.base+".")
	case san != "":
		put("dynamic_analysis_unsafe", "Met", "C++ runs under AddressSanitizer and UBSan in CI: "+san+".")
	default:
		unknown("dynamic_analysis_unsafe", "C/C++ without a sanitizer run.")
	}
	asserts := or(san, r.workflowURL(`\bdebug\b|CMAKE_BUILD_TYPE=Debug`))
	switch {
	case len(cxx) > 0 && asserts != "":
		put("dynamic_analysis_enable_assertions", "Met", "Tests run with assertions on (debug builds): "+asserts+".")
	case len(cxx) == 0 && dyn != "" && r.workflowURL(`python3?\s+-\w*O|PYTHONOPTIMIZE`) == "":
		put("dynamic_analysis_enable_assertions", "Met", "Python's assertions are on in every test run: "+dyn+".")
	default:
		unknown("dynamic_analysis_enable_assertions", "No assertion-enabled dynamic analysis found.")
	}

	for _, c := range ownerOnlyOrder {
		unknown(c, "Only the owner can answer this.")
	}
	out := make(Answers, 0, len(Passing))
	var missing []string
	for _, c := range Passing {
		x, ok := a[c]
		if !ok { // a criterion this function forgot is a bug, not a `?`
			missing = append(missing, c)
		}
		out = append(out, x)
	}
	if len(missing) > 0 {
		return nil, failure("bestpractices: no answer for %s", strings.Join(missing, ", "))
	}
	return out, nil
}

// maintained: the last commit is known and at most 365 days before today.
func maintained(last, today string) bool {
	if last == "" {
		return false
	}
	l, err1 := time.Parse("2006-01-02", last)
	t, err2 := time.Parse("2006-01-02", today)
	if err1 != nil || err2 != nil {
		return false
	}
	return int(t.Sub(l).Hours()/24) <= 365
}

// JSON is the .bestpractices.json text: <criterion>_status and
// <criterion>_justification for each answer, as json.dumps(indent=2).
func (a Answers) JSON() string {
	var b strings.Builder
	b.WriteString("{")
	for i, x := range a {
		if i > 0 {
			b.WriteString(",")
		}
		fmt.Fprintf(&b, "\n  %s: %s,\n  %s: %s", jsonString(x.Criterion+"_status"), jsonString(x.Status),
			jsonString(x.Criterion+"_justification"), jsonString(x.Why))
	}
	if len(a) > 0 {
		b.WriteString("\n")
	}
	b.WriteString("}\n")
	return b.String()
}

// Summary counts the answers by status: "? 11, Met 46, N/A 10".
func (a Answers) Summary() string {
	counts := map[string]int{}
	for _, x := range a {
		counts[x.Status]++
	}
	keys := make([]string, 0, len(counts))
	for k := range counts {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	parts := make([]string, len(keys))
	for i, k := range keys {
		parts[i] = fmt.Sprintf("%s %d", k, counts[k])
	}
	return strings.Join(parts, ", ")
}
