# GeoProvenance, drawn three ways — index

The diagrams live in three files, one per view. This page is only a pointer; **nothing is
drawn here**, so there is no second copy to drift out of date.

| Diagram | File | Answers |
|---|---|---|
| System architecture | [`ARCHITECTURE.md`](./ARCHITECTURE.md) | How the parts fit together — five layers, which file each box is, who owns it, what is proven |
| Data flow | [`DFD.md`](./DFD.md) | How information moves — context, then one level down, split into the recording half and the reading-back half |
| Use cases | [`USE_CASES.md`](./USE_CASES.md) | What a person can do with it — three actors, ten capabilities, and which have actually been done |

All three are drawn as mermaid, use plain English per `RULES.md` §7.5, and draw anything
written-but-unproven with a **dashed** outline per `RULES.md` §11.4. Each carries its own
"last checked against the code" date.

`ARCHITECTURE.md` §2 records where the built system departs from
`geoprovenance_research.md` §5.1, which was drawn before the code and is wrong in five
ways. The research report is **left as it stands**, as was done for its §7.3 example. Note
that `DEVELOPMENT.md` (formerly the top-level `README.md`) still defines the A/B/C split by pointing at §5.1's boxes.
