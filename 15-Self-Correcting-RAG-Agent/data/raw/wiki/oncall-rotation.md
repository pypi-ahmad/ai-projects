# Engineering On-Call Rotation

Backend and platform engineers rotate through a weekly on-call shift, tracked in PagerDuty.
The on-call engineer carries a phone with alerts enabled and is expected to acknowledge a page
within fifteen minutes.

If an alert is not acknowledged within fifteen minutes, PagerDuty automatically escalates to
the secondary on-call engineer, and after another fifteen minutes, to the engineering manager.
Repeated missed pages are reviewed in the next team retro, not treated as a disciplinary matter.

Swapping on-call shifts is allowed with a teammate's agreement; just update the PagerDuty
schedule so alerts route correctly.
