# Source inventory (Moorfunke tenant)

Rule: only verified open licences. "unclear" means not usable. Fill one row per source, then copy the
verified rows into `tenants/moorfunke.yaml`. The loader rejects unclear licences.

The verified sources below are used by the fictional tenant `tenants/moorfunke.yaml` ("Moorfunke e.V.").
`tenants/demo.yaml` stays the generic, empty white-label example (tests depend on it).

Checked on: 2026-10-14

## Requirements for the corpus
- 8-10 sources on environmental topics (for example climate, biodiversity, energy, Green IT).
- At least 2 German and 2 English sources.
- At least 2 sources with statistics, and at least 1 clearly dated or outdated source.
- Licence verified on the publisher's own page, with that page's URL.
- Redistribution checked: may the repo contain a copy?

Result: 12 sources, 6 German + 6 English, all 12 contain statistics. Dated/outdated pairs where a newer
source updates an older figure:
- `eea-ghg-trends-2024` (published 31 Oct 2024: projected net GHG cut by 2030 = 49% vs 1990; net emissions
  -31% 1990-2022) is updated by `eea-ghg-trends-2025` (published 06 Nov 2025: 47% with existing measures,
  54% with additional measures; -36% 1990-2023).
- `destatis-strom-2024` (12 Mar 2025: renewables share of electricity fed into the grid in 2024 = 59.4%) is
  revised by `destatis-strom-2025` (06 Mar 2026: "2024: 59,5 %"; 2025 = 58.6%).
- `uba-erneuerbare-pm-2024` (UBA press release 50/2024, 12 Dec 2024: renewable share of gross electricity
  consumption "rund 54 Prozent" for 2024, about 285 TWh, preliminary; 52.5% for 2023) is updated by
  `uba-erneuerbare-2025` (5 Mar 2026: 54.4% for 2024, 55.1% for 2025, 290 TWh; 23.8% of gross final energy
  consumption in 2025).
- Further dated material: `ec-cloud-energy-2020` (2020 study: data centres 2.7% of EU electricity demand in
  2018, projected 3.2% by 2030); `dewiki-green-it` contains a forecast marked "(Stand 2008)";
  `owid-co2-emissions` says "we now emit over 35 billion tonnes" without a year (first published June 2020).

## Sources

| id | title | url | language | kind | licence | licence page | redistributable | statistics | published | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| eea-ghg-trends-2025 | Total net greenhouse gas emission trends and projections in Europe | https://www.eea.europa.eu/en/analysis/indicators/total-greenhouse-gas-emission-trends | en | web | CC BY 4.0 | https://www.eea.europa.eu/en/legal-notice | yes | yes | 2025-11-06 | "Published 06 Nov 2025" on page. Living indicator page: content may change at the next edition; re-check date before fetching. ~5k words incl. navigation. |
| eea-ghg-trends-2024 | 8th EAP headline indicator 2024: Total net greenhouse gas emission trends and projections in Europe | https://www.eea.europa.eu/en/analysis/publications/european-union-8th-environment-action-programme-1/indicators/01-total-net-greenhouse-gas-emission-trend/@@download/file | en | pdf | CC BY 4.0 | https://www.eea.europa.eu/en/legal-notice | yes | yes | 2024-10-31 | 8-page PDF, "Published 31 Oct 2024" in the document. Outdated by eea-ghg-trends-2025. EEA server returned 502/timeouts intermittently on 2026-10-14; retry. |
| eea-biodiversity-2025 | 1.1 State of Europe's biodiversity (Europe's environment 2025) | https://www.eea.europa.eu/en/europe-environment-2025/thematic-briefings/biodiversity-and-ecosystems/state-of-europes-biodiversity | en | web | CC BY 4.0 | https://www.eea.europa.eu/en/legal-notice | yes | yes | 2025-09-29 | ~1.4k words. E.g. "81% of habitats, 39% of birds and 62% of non-bird species ... poor or bad state". |
| owid-co2-emissions | CO₂ emissions | https://ourworldindata.org/co2-emissions | en | web | CC BY 4.0 | https://ourworldindata.org/faqs | yes | yes | 2020-06-10 | Page: "first published in June 2020. We made minor changes to the text in January 2024." Embedded charts use third-party data (their own terms); we use the OWID text only. ~4k words. |
| owid-biodiversity | Biodiversity | https://ourworldindata.org/biodiversity | en | web | CC BY 4.0 | https://ourworldindata.org/faqs | yes | yes | 2022-12-19 | Page: "First published December 2022; last updated October 2026." Discusses the Living Planet Index as "widely quoted but misunderstood" (good for contested cases). ~3.9k words. |
| ec-cloud-energy-2020 | Green and Digital: study shows technical and policy options to limit surge in energy consumption for cloud and data centres | https://commission.europa.eu/news-and-media/news/green-and-digital-study-shows-technical-and-policy-options-limit-surge-energy-consumption-cloud-and-2020-11-09_en | en | web | CC BY 4.0 | https://commission.europa.eu/legal-notice_en | yes | yes | 2020-11-09 | News article, "9 November 2020" on page (page metadata says 2021-10-15, a site migration date; we use the visible date). ~1k words. Green IT, dated. |
| destatis-strom-2024 | Stromerzeugung 2024: 59,4 % aus erneuerbaren Energieträgern (PM Nr. 091) | https://www.destatis.de/DE/Presse/Pressemitteilungen/2025/03/PD25_091_43312.html | de | web | Destatis copyright notice (reproduction and distribution with source attribution) | https://www.destatis.de/DE/Service/Impressum/_inhalt.html | yes | yes | 2025-03-12 | "Pressemitteilung Nr. 091 vom 12. März 2025". Older figure (59.4%) revised by destatis-strom-2025. Attribution: "Statistisches Bundesamt (Destatis)". |
| destatis-strom-2025 | Stromerzeugung aus Photovoltaik und Erdgas erreicht im Jahr 2025 neue Höchstwerte (PM Nr. 073) | https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/03/PD26_073_43312.html | de | web | Destatis copyright notice (reproduction and distribution with source attribution) | https://www.destatis.de/DE/Service/Impressum/_inhalt.html | yes | yes | 2026-03-06 | "Pressemitteilung Nr. 073 vom 6. März 2026". Contains a table 2024 vs 2025. |
| dewiki-green-it | Green IT (de.wikipedia, revision 267912244) | https://de.wikipedia.org/wiki/Green_IT?oldid=267912244 | de | web | CC BY-SA 4.0 | https://de.wikipedia.org/wiki/Wikipedia:Weiternutzung | yes (share-alike) | yes | null | Article has no single publication date; pinned to revision 267912244 (last edit 13 June 2026). Contains dated figures, e.g. forecast "(Stand 2008)", ICT electricity use 2007. Share-alike: a copy in the repo must stay CC BY-SA 4.0 with attribution. ~4.4k words. |
| dewiki-rechenzentrum | Rechenzentrum (de.wikipedia, revision 271299132) | https://de.wikipedia.org/wiki/Rechenzentrum?oldid=271299132 | de | web | CC BY-SA 4.0 | https://de.wikipedia.org/wiki/Wikipedia:Weiternutzung | yes (share-alike) | yes | null | Pinned to revision 271299132 (last edit 13 Oct 2026). Section "Kennzahlen": 205 TWh worldwide 2018 (model-based estimate), 448 TWh for 2025. ~10k words: chunk only the relevant sections if too large. |
| uba-erneuerbare-pm-2024 | Mehr Strom aus erneuerbaren Energien (UBA Pressemitteilung Nr. 50/2024) | https://www.umweltbundesamt.de/presse/pressemitteilungen/mehr-strom-aus-erneuerbaren-energien | de | web | Creative Commons Namensnennung – Nicht kommerziell – keine Bearbeitungen 4.0 International (CC BY-NC-ND 4.0) | https://www.umweltbundesamt.de/datenschutz-haftung-urheberrecht | no (NC-ND, see Licence risk) | yes | 2024-12-12 | "Pressemitteilung No. 50/2024 \| 12.12.2024". Preliminary figures, superseded by uba-erneuerbare-2025. ~1.6k words. Fetch script only, no repo copy. |
| uba-erneuerbare-2025 | Erneuerbare Energien in Deutschland: Wachstum 2025 verhalten (UBA) | https://www.umweltbundesamt.de/themen/erneuerbare-energien-in-deutschland-wachstum-2025 | de | web | Creative Commons Namensnennung – Nicht kommerziell – keine Bearbeitungen 4.0 International (CC BY-NC-ND 4.0) | https://www.umweltbundesamt.de/datenschutz-haftung-urheberrecht | no (NC-ND, see Licence risk) | yes | 2026-03-05 | Date "05.03.2026" shown on page; page was not marked as updated later. ~1.8k words. Updates the 2024 press release. Fetch script only, no repo copy. |

### Licence risk (UBA, CC BY-NC-ND 4.0)

The user decided on 2026-10-14 to include UBA sources despite their licence and treats the project as
non-commercial. The risk stays visible:
- **NC (non-commercial)** conflicts with commercial white-label use. If the assistant is ever offered to an NGO
  as a paid product, or run commercially, these two sources must be removed.
- **ND (no derivatives)** conflicts with chunking, excerpting or rewording for retrieval and with
  generated summaries that could count as adaptations. Whether RAG processing is a "derivative" is a legal
  question we did not resolve; we treat it as a risk accepted by the user.
- Hence `redistributable: false`: the repository holds no copy; the fetch script downloads into gitignored
  `data/raw/`. Attribution ("Umweltbundesamt", licence name, link) is required in any output.
- UBA's page limits the licence to "vom Umweltbundesamt selbst erstellte Objekte ... soweit nicht anders gekennzeichnet"; third-party
  images or charts on those pages are not covered (we use text only).
- **OWID (CC BY 4.0) has a similar edit condition**: its FAQ says "You must not edit the material" (see the
  licence quotes). Chunking for retrieval is not editing in the usual sense, but excerpting, rewording or
  summarising OWID text could be read as editing. Keep OWID text unaltered in chunks and cite it; this
  is a noted, unresolved legal question like the UBA ND point.

### Licence quotes (verified 2026-10-14 on the publisher's own page)

| publisher | licence page | exact quote |
|---|---|---|
| EEA | https://www.eea.europa.eu/en/legal-notice | "EEA materials are published under the CC-BY license" (links to creativecommons.org/licenses/by/4.0); "may be re-used without prior permission, free of charge, for commercial or non-commercial purposes, provided that the EEA is always acknowledged as the original source of the material and that the original meaning or message of the content is not distorted." Exception: "The above-mentioned permissions do not apply to content supplied by third parties." |
| Our World in Data | https://ourworldindata.org/faqs | "You can republish or reproduce our writing, online or in print, for free and without permission"; attribution line "Republished here under a Creative Commons license" (links to CC BY 4.0); "Data produced by us falls under our permissive CC BY license". Conditions: "You must not edit the material, except to reflect relative changes in time, location and editorial style." Third-party data: "subject to the license terms of those providers." |
| European Commission | https://commission.europa.eu/legal-notice_en | "Unless otherwise indicated (e.g. in individual copyright notices), content owned by the EU on this website is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence" (Commission Decision 2011/833/EU). Excluded: trade marks/logos and content not owned by the EU. |
| Destatis | https://www.destatis.de/DE/Service/Impressum/_inhalt.html | "Vervielfältigung und Verbreitung, auch auszugsweise, mit Quellennachweis gestattet." Applies "soweit bei dem jeweiligen Produkt/Internetseite keine ergänzenden oder anderslautenden Angaben ausgewiesen sind". Exception: header/theme images "© Alle Rechte vorbehalten. Eine Weiterverbreitung durch Dritte ist nicht gestattet." (we use text only). GENESIS data: "Datenlizenz Deutschland - Namensnennung - Version 2.0". |
| Umweltbundesamt | https://www.umweltbundesamt.de/datenschutz-haftung-urheberrecht | "Soweit nicht anders gekennzeichnet, stehen vom Umweltbundesamt selbst erstellte Objekte, Grafiken, Tondokumente, Videosequenzen und Texte auf dieser Website unter einer Creative Commons Namensnennung – Nicht kommerziell – keine Bearbeitungen 4.0 International Lizenz" (links to CC BY-NC-ND 4.0). Separate sentence on data: "Soweit nicht anders gekennzeichnet, ist die Nutzung von Daten im Sinne des § 12a EGovG zulässig." |
| Wikipedia (de) | https://de.wikipedia.org/wiki/Wikipedia:Weiternutzung | "Grundsätzlich dürfen alle Texte der Wikipedia gemäß der Creative-Commons-Lizenz CC-BY-SA 4.0 (Namensnennung - Weitergabe unter gleichen Bedingungen 4.0) genutzt werden." Article footer: "Der Text ist unter der Lizenz „Creative-Commons Namensnennung – Weitergabe unter gleichen Bedingungen" verfügbar" (links to by-sa/4.0). |

## robots.txt and terms (only for sources you fetch automatically)

All checked on 2026-10-14 with User-agent `*` rules (no rule targets our user agent specifically).

| site | robots.txt allows? | checked on | terms of use quote |
|---|---|---|---|
| www.eea.europa.eu | yes. Disallows `*/assets/*`, `/api`, `/images`, search/RSS paths; `/en/analysis/...`, `/en/europe-environment-2025/...` and `.../@@download/file` are not disallowed | 2026-10-14 | "may be re-used without prior permission, free of charge, for commercial or non-commercial purposes, provided that the EEA is always acknowledged" |
| ourworldindata.org | yes. robots.txt contains only a `Sitemap:` line, no Disallow | 2026-10-14 | "You can republish or reproduce our writing, online or in print, for free and without permission" |
| commission.europa.eu | yes. Disallows only `/core/`, `/profiles/`, `/admin/`, `/search/`, user paths; `/news-and-media/news/...` allowed | 2026-10-14 | "content owned by the EU on this website is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence" |
| www.destatis.de | yes, with `Crawl-delay: 30`. Disallows `/SiteGlobals/` (with exceptions) and `/GPStatistik/servlets/MCRSearchServlet`; `/DE/Presse/Pressemitteilungen/...` allowed. Fetch script must wait 30 s between requests | 2026-10-14 | "Vervielfältigung und Verbreitung, auch auszugsweise, mit Quellennachweis gestattet." |
| www.umweltbundesamt.de | yes, with `crawl-delay: 10`. Disallows `/search`, `/datensuche`, `/admin/`, `/core/`, user paths; `/presse/pressemitteilungen/...` and `/themen/...` are not disallowed. Fetch script must wait 10 s between requests | 2026-10-14 | "Soweit nicht anders gekennzeichnet, stehen ... Texte auf dieser Website unter einer Creative Commons Namensnennung – Nicht kommerziell – keine Bearbeitungen 4.0 International Lizenz" |
| de.wikipedia.org | yes for `/wiki/<Article>` (incl. `?oldid=`). Disallows `/w/` (so not `/w/index.php?oldid=`), `/api/` (except listed exceptions), `/wiki/Spezial:` | 2026-10-14 | "Grundsätzlich dürfen alle Texte der Wikipedia gemäß der Creative-Commons-Lizenz CC-BY-SA 4.0 ... genutzt werden." |

## Rejected candidates

| candidate | reason |
|---|---|
| IPCC reports (ipcc.ch) | Not an open licence. https://www.ipcc.ch/copyright/ (2026-10-14): "For such personal, non-commercial usages, reproduction of limited number of figures or short excerpts of IPCC material is authorized free of charge and without formal written permission"; other uses need written permission. |
| Umweltbundesamt, further UBA publications | Not rejected for licence reasons: two UBA pages were accepted on 2026-10-14 by user decision (see Licence risk). More UBA texts are not added to keep the corpus small. |
| Bundesamt für Naturschutz (bfn.de) | https://www.bfn.de/impressum (2026-10-14): "Das BfN behält sich alle Rechte vor." Texts "dürfen ohne vorherige Zustimmung des BfN nicht vervielfältigt, verbreitet oder anderweitig genutzt werden". |
| Copernicus Climate Change Service (climate.copernicus.eu, e.g. European State of the Climate) | Ambiguous, so treated as unclear: https://climate.copernicus.eu/disclaimer-privacy (2026-10-14) says "Reproduction of the publically available content of this website is authorised, provided the source is acknowledged", but also "Commercial use or sale of the pictures and data, even in electronically manipulated form, is prohibited", and no licence is stated for the ESOTC reports themselves. |
| EC study "Energy-efficient Cloud Computing Technologies and Policies for an Eco-friendly Cloud Market" (full report) | Not selected: too large for the CPU-only setup; the Commission's news summary (ec-cloud-energy-2020) is used instead. Licence not checked separately. |
| bund-hamburg.de | Out of scope without written permission (ADR-001); not accessed. |

## Fictional NGO name check

Chosen name: **Moorfunke e.V.**, slug `moorfunke` (tenant file `tenants/moorfunke.yaml`).
Fantasy name (German "Moor" = peatland/bog, "Funke" = spark). It is fictional; all NGO facts come only
from our synthetic documents.

Web searches on 2026-10-14 (WebSearch tool):

| query | result |
|---|---|
| `"Moorfunke e.V."` | No organisation of that name found. Hits were unrelated peatland bodies (IG Moorschutz, MoKli project, MOORWELTEN). |
| `"Moorfunke" Umwelt Verein` | No hit mentioning "Moorfunke". Closest topical match: Verein Dachauer Moos e.V. (different name). |
| `"Moorfunke" Naturschutz OR Klimaschutz OR environmental organisation` | No result mentions "Moorfunke" in any context. |
| `"Kranichgrund e.V."` (first candidate) | No organisation found, but results were dominated by real crane-protection groups (Kranichschutz Deutschland); rejected to avoid confusion with them. |

Limitation: a web search cannot prove that no small local association uses the name; the official
Vereinsregister (handelsregister.de / gemeinsames Registerportal) was not searched.

## bund-hamburg.de (optional second tenant)

Status: not usable without written permission (ADR-001).
Paste here, from your own browser: robots.txt text, usage sentences from the imprint, date checked.
