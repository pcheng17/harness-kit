# What a good test looks like

Examples below span C++ simulation code and full-stack (TS/JS) code, since both come up. The principle is the same in both: assert on public behavior, with expected values from a source of truth independent of the implementation.

## C++ / physics engine examples

**Bad — tautological.** Recomputes the same formula the code uses; can never catch a wrong formula.

```cpp
TEST_CASE("integrator advances velocity") {
    RigidBody body{.mass = 2.0, .velocity = {0, 0, 0}};
    Vec3 force{0, -9.8 * body.mass, 0};
    integrate(body, force, /*dt=*/0.1);
    REQUIRE(body.velocity.y == Approx(force.y / body.mass * 0.1)); // same formula as prod code
}
```

**Good — expected value from an independent source (analytical solution / worked example).**

```cpp
TEST_CASE("free-falling body matches closed-form projectile motion after 1s") {
    RigidBody body{.mass = 1.0, .position = {0, 100, 0}, .velocity = {0, 0, 0}};
    Simulation sim;
    sim.addBody(body);

    sim.step(/*dt=*/1.0); // gravity = -9.8 m/s^2

    // y(t) = y0 - 0.5*g*t^2 — worked out independently, not derived from the integrator
    REQUIRE(sim.bodies()[0].position.y == Approx(100 - 0.5 * 9.8 * 1.0 * 1.0).margin(1e-6));
}
```

**Good — invariant-based, when there's no simple closed form.** Conservation laws are a source of truth the implementation doesn't get to define.

```cpp
TEST_CASE("elastic collision conserves total kinetic energy") {
    Simulation sim = twoBodyElasticCollisionSetup();
    double energyBefore = sim.totalKineticEnergy();

    sim.stepUntil(/*event=*/CollisionOccurred);

    REQUIRE(sim.totalKineticEnergy() == Approx(energyBefore).margin(1e-9));
}
```

Test at the `Simulation`/`RigidBody` public API (the seam), not by reaching into the broad-phase grid or the solver's internal Jacobians — those are implementation details that should be free to change (switching solvers, spatial partitioning schemes) without breaking the test.

### Floating point

- Never use `==` on floats/doubles. Use an epsilon comparison (`Approx(...).margin(...)` in Catch2, `EXPECT_NEAR` in GoogleTest).
- Pick the margin from the physics, not from "whatever makes it pass" — e.g. margin proportional to the energy scale of the system, or a few ULPs for a value that should be exact.
- If the engine must be bit-reproducible across runs/platforms, that's its own explicit test (fixed-seed replay, cross-platform hash comparison) — don't conflate it with correctness tests.

## Full-stack (TS/JS) examples

**Bad — implementation-coupled.** Verifies through a side channel (the DB) instead of the interface under test.

```ts
test("checkout creates an order", async () => {
  await checkout(cart);
  const row = await db.query("SELECT * FROM orders WHERE cart_id = ?", [cart.id]);
  expect(row).toBeDefined(); // asserts DB shape, not the checkout API's behavior
});
```

**Good — asserts through the public interface, with an expected value from the spec/fixture, not recomputed.**

```ts
test("checkout with a valid cart returns a confirmed order", async () => {
  const cart = fixtures.cartWithTwoItems(); // known-good fixture, not built ad hoc in the test
  const order = await checkout(cart);

  expect(order.status).toBe("confirmed");
  expect(order.total).toBe(4599); // from the fixture's known prices, in cents
});
```

Test at the HTTP/service boundary a real caller uses. Reserve DB assertions for tests that are specifically about persistence (e.g. "order survives a process restart").

## Where these live

- C++ engine/simulation tests: alongside the module under test, using the project's existing framework (Catch2/GoogleTest) — check for a `tests/` or `*_test.cpp` convention before adding a new one.
- Full-stack tests: colocate unit tests with source; integration/API tests typically live in a top-level `integration/` or `e2e/` directory hitting a real (or containerized) backend, not a mocked one.
