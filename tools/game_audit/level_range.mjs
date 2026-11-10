// Where a shot comes down on level ground, by bisection on its height over the distance.

/** Halvings of the bracket: 60 take any range a weapon has below a nanometre. */
const ITERATIONS = 60;

/**
 * Horizontal distance at which a shot is back at the height of the weapon's ground.
 * @param {(distance: number) => number} height - height of the shot above that ground at a horizontal distance,
 *   meters; positive from the weapon to the landing point and not positive beyond it
 * @param {number} far - a distance beyond the landing point, meters
 * @returns {number} - meters; 0 for a shot that starts on or under the ground
 * @throws {RangeError} when the shot is still above the ground at `far`
 */
export function levelRange(height, far) {
    if (!(height(0) > 0)) return 0;
    if (height(far) > 0) throw new RangeError(`the shot is still ${height(far)} m up at ${far} m`);
    let near = 0;
    for (let i = 0; i < ITERATIONS; i++) {
        const middle = (near + far) / 2;
        if (height(middle) > 0) near = middle;
        else far = middle;
    }
    return near;
}
