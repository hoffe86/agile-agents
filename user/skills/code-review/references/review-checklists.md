# Review Checklists

Detailed checklists for each review dimension. The review agents should use these as their investigation guide — they don't need to report on every item, only findings that are actually present.

---

## Architecture & Design Checklist

### SOLID Principles
- [ ] Single Responsibility: Are there god classes doing too many things? (>5 injected dependencies is a smell)
- [ ] Open/Closed: Are extension points available, or does adding features require modifying core classes?
- [ ] Liskov Substitution: Are interface implementations truly interchangeable?
- [ ] Interface Segregation: Are interfaces focused, or do implementors have empty/throwing methods?
- [ ] Dependency Inversion: Do high-level modules depend on abstractions, not concretes?

### Dependency Injection
- [ ] Duplicate registrations (same service registered multiple ways)
- [ ] Lifetime mismatches (singleton depending on scoped/transient)
- [ ] Service locator anti-pattern (injecting `IServiceProvider` to resolve services manually)
- [ ] Sync-over-async in DI factories (`.GetAwaiter().GetResult()` during composition)
- [ ] Missing registrations (services referenced but not registered)

### Layering & Boundaries
- [ ] Layer violations (lower layers referencing higher ones)
- [ ] Circular project/package references
- [ ] Abstraction layers that aren't actually abstract (reference implementation details)
- [ ] Shared projects that should be split

### Async Patterns
- [ ] `async void` methods (except event handlers)
- [ ] `.Wait()`, `.Result`, `.GetAwaiter().GetResult()` (sync-over-async)
- [ ] Fire-and-forget `Task.Run` without error handling
- [ ] Missing `CancellationToken` propagation
- [ ] Missing `ConfigureAwait(false)` in library code

### Error Handling
- [ ] Global exception handler present and returns safe responses
- [ ] Exception details leaked to clients (stack traces, internal messages)
- [ ] Exceptions swallowed silently (catch with no logging or rethrow)
- [ ] Inconsistent error response formats across endpoints
- [ ] Catch-all `Exception` that wraps without logging context

### Configuration
- [ ] Hardcoded values that should be configurable
- [ ] Options pattern used consistently
- [ ] Environment-specific configuration separated properly
- [ ] Magic strings/numbers in business logic

---

## Security Checklist

### Authentication & Authorization
- [ ] All API endpoints require authentication (check for missing `[Authorize]`, `RequireAuthorization()`)
- [ ] Authorization is explicit, not implicit (don't rely on middleware path matching alone)
- [ ] Fallback/default policy is deny-by-default, not allow-all
- [ ] JWT validation is strict (issuer validated, HTTPS metadata required in production)
- [ ] Token expiration is checked
- [ ] Client-supplied identity fields are validated against server-side claims

### Input Validation
- [ ] Request DTOs have validation attributes or explicit validation
- [ ] User input is sanitized before use in: SQL queries, file paths, URLs, shell commands, prompts
- [ ] URL parameters are encoded (`Uri.EscapeDataString`)
- [ ] File uploads are validated (type, size, content)
- [ ] JSON deserialization has depth/size limits

### Secrets Management
- [ ] No hardcoded secrets in source code (API keys, connection strings, tokens)
- [ ] No secrets in Dockerfile build args or ENV that persist in layers
- [ ] No secrets committed in pipeline YAML or config files
- [ ] User secrets or Key Vault used for development secrets
- [ ] Secret rotation is possible without code changes

### CORS
- [ ] No `AllowAnyOrigin()` in production
- [ ] Origin allowlist is environment-specific
- [ ] Only one CORS policy applied (not stacked/overriding)

### HTTP Security Headers
- [ ] HSTS enabled
- [ ] `X-Content-Type-Options: nosniff`
- [ ] `X-Frame-Options` or CSP `frame-ancestors`
- [ ] `Strict-Transport-Security` with adequate max-age

### Logging Security
- [ ] Tokens/secrets never logged (check error handlers, HTTP logging config)
- [ ] PII is redacted or not logged
- [ ] HTTP logging level is restricted (not `All`)
- [ ] Log sinks are access-controlled

### Dependencies
- [ ] No known vulnerable package versions
- [ ] Dependency scanning configured (Dependabot, Mend/WhiteSource, Snyk)
- [ ] Warning suppressions (`NU1605`, etc.) are justified
- [ ] End-of-life framework versions are flagged

### Rate Limiting & DoS
- [ ] Rate limiting covers all public API routes
- [ ] External service calls have timeouts
- [ ] Circuit breakers for critical downstream dependencies
- [ ] Request size limits configured

---

## Clean Code Checklist

### Dead Code
- [ ] Unused methods, classes, or files
- [ ] Unreachable code paths
- [ ] Stale documentation referencing removed features
- [ ] TODO/FIXME/HACK comments that are stale
- [ ] Empty projects or test projects with no source files

### Naming
- [ ] Language-standard naming conventions followed consistently
- [ ] Extension class naming is consistent (singular vs plural)
- [ ] No typos in identifiers
- [ ] Names accurately describe purpose (no misleading names)

### Complexity
- [ ] Methods over ~30 lines should be decomposed
- [ ] Nesting depth > 3 levels is a smell
- [ ] Cyclomatic complexity is reasonable
- [ ] Switch/if-else chains that should be polymorphic

### Duplication
- [ ] Copy-pasted code across classes (especially builders, factories, handlers)
- [ ] Duplicate DI registrations or JSON converter configs
- [ ] Similar error handling patterns that could be unified

### Testability
- [ ] Classes create their own dependencies (`new` inside business logic)
- [ ] Static method calls that block testing
- [ ] Constructor with too many parameters (>6)
- [ ] Tightly coupled to framework types

### Resource Management
- [ ] `IDisposable` resources properly disposed (using/await using)
- [ ] Channels completed with `Writer.TryComplete()`
- [ ] `HttpClient` used via `IHttpClientFactory`, not `new`
- [ ] Database connections returned to pool

### Documentation
- [ ] Public API XML docs present and accurate
- [ ] README reflects current architecture
- [ ] Instruction files match actual code structure
- [ ] No unclosed or empty doc tags

---

## Test Quality Checklist

### Coverage
- [ ] All business-critical classes have dedicated tests
- [ ] Authentication/authorization paths are tested
- [ ] Error/exception paths are tested
- [ ] Edge cases (null, empty, boundary values) are tested

### Quality
- [ ] Tests follow Arrange-Act-Assert pattern
- [ ] Test names follow `Method_Condition_ExpectedResult` or similar convention
- [ ] Each test verifies one behavior
- [ ] Tests assert outcomes, not implementation details

### Mocking
- [ ] Mocks are focused (only mock what's needed)
- [ ] No reflection-based testing of private methods
- [ ] Mock verification is meaningful (not just "called once")
- [ ] `IServiceProvider` mocking minimized

### Isolation
- [ ] No shared mutable state between tests
- [ ] No test ordering dependencies
- [ ] Integration tests clearly separated from unit tests
- [ ] Tests that silently skip (missing config) are flagged

### Duplicates
- [ ] No duplicate test classes across test projects
- [ ] Test files map to the correct source project location
