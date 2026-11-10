// Tests of levelRange against the closed form of a parabola. Run: node --test tools/game_audit/
import { test } from "node:test";
import assert from "node:assert/strict";
import { levelRange } from "./level_range.mjs";

const G = 9.8;

/** Height of a drag-free shot fired at `degrees` with `speed` from `start` meters above the ground. */
function parabola(speed, degrees, start) {
    const angle = degrees * Math.PI / 180;
    return (distance) => start + distance * Math.tan(angle) - G * distance ** 2 / (2 * (speed * Math.cos(angle)) ** 2);
}

/** The same shot's landing distance in closed form. */
function closedForm(speed, degrees, start) {
    const angle = degrees * Math.PI / 180;
    const up = speed * Math.sin(angle);
    return speed * Math.cos(angle) * (up + Math.sqrt(up ** 2 + 2 * G * start)) / G;
}

test("a mortar-like shot lands where the closed form says, on both arcs and from a height", () => {
    for (const [speed, degrees, start] of [[110, 45, 0.02], [110, 88.8, 1.6], [142, 85, 3.5], [300, 0, 2.5], [95, 10, 0.6]]) {
        const range = levelRange(parabola(speed, degrees, start), 20000);
        assert.ok(Math.abs(range - closedForm(speed, degrees, start)) < 1e-6, `${speed} m/s at ${degrees} degrees: ${range}`);
    }
});

test("a barrel pointing down from a height reaches only the ground in front of it", () => {
    const range = levelRange(parabola(300, -25, 1.3), 20000);
    assert.ok(Math.abs(range - closedForm(300, -25, 1.3)) < 1e-6);
    assert.ok(range > 2.7 && range < 2.8, `${range}`);
});

test("a shot that starts on the ground has no range", () => {
    assert.equal(levelRange(parabola(110, 45, 0), 20000), 0);
    assert.equal(levelRange(() => -1, 100), 0);
});

test("a bracket that ends before the landing point is refused, not answered", () => {
    assert.throws(() => levelRange(parabola(110, 45, 1), 500), RangeError);
});
