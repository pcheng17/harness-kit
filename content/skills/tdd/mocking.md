# Mocking guidelines

Mock at the boundary of the system you don't control. Never mock the thing you're trying to verify, or a collaborator that's just an internal implementation detail — that's the implementation-coupled anti-pattern (see SKILL.md). If you're unsure whether to mock something, ask: "would a real caller ever substitute this?" If no, it's not a seam, don't mock it.

## What to mock

Genuine externalities:
- Wall-clock time, RNG seeds, hardware/OS-level I/O (disk, network sockets)
- Third-party services you don't own (payment gateway, external REST API)
- Anything nondeterministic or slow enough to make the test flaky/expensive for no benefit (real GPU device, real filesystem for a unit test)

## What NOT to mock

- **The math/physics itself.** Don't mock the solver, the broad-phase collision detector, or the integrator to test code that depends on them — that tests your mock's behavior, not the engine's. Use a real (possibly simplified/deterministic) `Simulation`, not a stub.
- **Your own database, in integration tests.** Use a real instance (test container, in-memory Postgres, sqlite) — a mocked DB can't catch a broken query or a migration mismatch.
- **Internal collaborators reachable through the public interface under test.** If `Simulation::step()` calls into `ConstraintSolver` internally, test `step()`'s observable output — don't mock `ConstraintSolver` to check it "was called."

## C++ patterns

Prefer dependency injection over mocking frameworks where the seam is simple:

```cpp
// A clock is a genuine externality — inject it, don't call std::chrono::now() directly.
class Simulation {
public:
    explicit Simulation(Clock& clock) : clock_(clock) {}
    void step();
private:
    Clock& clock_;
};

// Test seam: a fake clock, not a mocking framework.
class FakeClock : public Clock {
public:
    void advance(double dt) { time_ += dt; }
    double now() const override { return time_; }
private:
    double time_ = 0.0;
};
```

Reach for GoogleMock only at real external boundaries (e.g. a `NetworkTransport` interface for multiplayer sync, a `FileSystem` interface for save/load) — not for in-process collaborators like solvers, allocators, or spatial data structures. Those should be exercised for real; if they're slow, that's a signal to make a smaller/deterministic real instance (fewer bodies, fixed seed), not to fake their logic.

## Full-stack (TS/JS) patterns

```ts
// Genuine externality: mock the third-party payment API.
jest.mock("./paymentGateway", () => ({
  charge: jest.fn().mockResolvedValue({ status: "succeeded" }),
}));

// NOT a genuine externality: don't mock your own order repository —
// use a real test database instead.
test("checkout charges the card and creates an order", async () => {
  const order = await checkout(fixtures.cartWithTwoItems());
  expect(order.status).toBe("confirmed");
});
```

If you find yourself mocking more than one or two collaborators to get a unit under test to run, that's usually a sign the seam is drawn in the wrong place — test one level up, at the interface a real caller uses.
