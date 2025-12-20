function lerp(a: number, b: number, t: number) {
    return a + (b - a) * t;
}

function lerpColor(c1: string, c2: string, t: number) {
    const parse = (c: string) => {
        const r = parseInt(c.slice(1, 3), 16);
        const g = parseInt(c.slice(3, 5), 16);
        const b = parseInt(c.slice(5, 7), 16);
        return { r, g, b };
    };

    const a = parse(c1);
    const b = parse(c2);

    const r = Math.round(lerp(a.r, b.r, t));
    const g = Math.round(lerp(a.g, b.g, t));
    const b2 = Math.round(lerp(a.b, b.b, t));

    return `rgb(${r}, ${g}, ${b2})`;
}

export function animateSvgFillLoop(
    svgEl: SVGElement,
    duration = 5000
) {
    // const stops = ["#217bfe", "#078efb", "#ac87eb", "#217bfe"];
    const stops = ["#217bfe", "#ac87eb", "#078efb", "#217bfe"];
    const segments = stops.length - 1; // 3 segments
    const segmentDuration = duration / segments;

    function animate() {
        let start: number | null = null;

        function step(t: number) {
            if (!start) start = t;
            const elapsed = t - start;

            // position in the full loop (wraps using modulo)
            const loopPos = elapsed % duration;

            // which segment are we in?
            const segIndex = Math.floor(loopPos / segmentDuration);
            const segStart = segIndex * segmentDuration;

            const localT = (loopPos - segStart) / segmentDuration;

            const current = lerpColor(
                stops[segIndex],
                stops[segIndex + 1],
                localT
            );

            svgEl.style.fill = current;
            svgEl.style.stroke = current;

            requestAnimationFrame(step);
        }

        requestAnimationFrame(step);
    }

    animate();
}
