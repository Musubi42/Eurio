# Bench bimétal — qualité crop 2€ commémoratives

Échantillon : 40 demandés, seed=1, généré 2026-05-25 03:28:59

- Crops avec détection valide : **40**
- Crops suspects d'undercrop (r_pipe/r_probe < 0.85) : **5 (12 %)**
- Probe Otsu n'a pas pu se prononcer : **25**
- Erreurs (raw missing / unreadable) : **0**

**r_pipe/r_probe stats** : min=0.523  p25=0.821  med=0.892  p75=0.993  max=1.088

Légende : `r_pipe` = rayon choisi par la pipeline. `probe_r` = rayon Otsu+contour autour du même centre (oracle indépendant). Ratio < 0.85 → la pipeline a sous-cropé (typique bimétal : Hough vote anneau interne or au lieu du rim externe argent).

| country | year | theme | r_pipe/probe | r_pipe | probe_r | method | suspect | file |
|---|---|---|---|---|---|---|---|---|
| AD | 2023 | 30 years of the entry of the Principalit | 0.52 | 88 | 168 | yolo+hough+polish | ⚠ | `AD-2023-30-years-of-the-entry-of-the-p_afe6f7a6.jpg` |
| BE | 2005 | Belgium-Luxembourg Economic Union | 0.72 | 210 | 291 | yolo+hough | ⚠ | `BE-2005-belgium-luxembourg-economic-un_b42923e8.jpg` |
| BE | 2016 | 2016 Summer Olympics – Rio de Janeiro | 0.73 | 153 | 208 | yolo+hough+polish | ⚠ | `BE-2016-2016-summer-olympics-rio-de-ja_9efd37f6.jpg` |
| AD | 2022 | Currency Agreement between Andorra and E | 0.79 | 130 | 163 | yolo+hough | ⚠ | `AD-2022-currency-agreement-between-and_551727f0.jpg` |
| BE | 2016 | International Missing Children's Day | 0.85 | 100 | 117 | yolo+hough | ⚠ | `BE-2016-international-missing-children_fd5e8f82.jpg` |
| AD | 2017 | 100 years of the anthem of Andorra | n/a | 149 | — | yolo+hough+polish |  | `AD-2017-100-years-of-the-anthem-of-and_d789913f.jpg` |
| AD | 2020 | 27th Ibero-American Summit in Andorra | n/a | 49 | — | yolo+hough |  | `AD-2020-27th-ibero-american-summit-in-_c06e5abc.jpg` |
| AD | 2024 | UCI Mountain Bike MTB World Championship | n/a | 136 | — | yolo+hough |  | `AD-2024-uci-mountain-bike-mtb-world-ch_a7f2e526.jpg` |
| BE | 2012 | 75th anniversary of the Queen Elisabeth  | n/a | 100 | — | yolo+hough |  | `BE-2012-75th-anniversary-of-the-queen-_d6f66856.jpg` |
| BE | 2010 | Belgian Presidency of the Council of the | n/a | 89 | — | yolo+hough |  | `BE-2010-belgian-presidency-of-the-coun_5ee7dc76.jpg` |
| AD | 2022 | Andorra–European Union relations | n/a | 175 | — | yolo+hough |  | `AD-2022-andorra-european-union-relatio_ed897b76.jpg` |
| BE | 2013 | 100 years of Royal Meteorological Instit | n/a | 88 | — | yolo+hough |  | `BE-2013-100-years-of-royal-meteorologi_4bfc8381.jpg` |
| AT | 2018 | 100 years since the foundation of the Re | n/a | 166 | — | yolo+hough+polish |  | `AT-2018-100-years-since-the-foundation_238b2e85.jpg` |
| BE | 2020 | International Year of Plant Health | n/a | 199 | — | yolo+hough |  | `BE-2020-international-year-of-plant-he_f8ccbd06.jpg` |
| BE | 2019 | 450 years since the death of Pieter Brue | n/a | 180 | — | yolo+hough |  | `BE-2019-450-years-since-the-death-of-p_954be4c7.jpg` |
| BE | 2014 | 150 years of the Belgian Red Cross | n/a | 148 | — | yolo+hough+polish |  | `BE-2014-150-years-of-the-belgian-red-c_d3cb3848.jpg` |
| BE | 2020 | Jan van Eyck | n/a | 102 | — | yolo+hough |  | `BE-2020-jan-van-eyck_25635664.jpg` |
| BE | 2018 | 50 years since the launch of European sa | n/a | 161 | — | yolo+hough+polish |  | `BE-2018-50-years-since-the-launch-of-e_e2ae6bce.jpg` |
| BE | 2015 | European Year for Development | n/a | 179 | — | yolo+hough+polish |  | `BE-2015-european-year-for-development_5fc22b6c.jpg` |
| BE | 2006 | Renovation of the Atomium in Brussels | n/a | 84 | — | yolo+hough |  | `BE-2006-renovation-of-the-atomium-in-b_87a5710b.jpg` |
| AD | 2021 | 100 years since the coronation of Our La | n/a | 181 | — | yolo+hough |  | `AD-2021-100-years-since-the-coronation_a4ed6bb0.jpg` |
| AT | 2005 | 50th anniversary of the Austrian State T | n/a | 96 | — | yolo+hough+polish |  | `AT-2005-50th-anniversary-of-the-austri_cf1aacef.jpg` |
| AD | 2025 | Bearded vulture | n/a | 103 | — | yolo+hough+polish |  | `AD-2025-bearded-vulture_d47e93e9.jpg` |
| AD | 2023 | Summer solstice fire festivals in the Py | n/a | 149 | — | yolo+hough+polish |  | `AD-2023-summer-solstice-fire-festivals_d7285548.jpg` |
| AD | 2020 | 50 years since Andorra's introduction of | n/a | 42 | — | yolo+hough |  | `AD-2020-50-years-since-andorra-s-intro_d5f60f23.jpg` |
| BE | 2019 | 25 years since the creation of the Europ | n/a | 116 | — | yolo+hough |  | `BE-2019-25-years-since-the-creation-of_b6c0b229.jpg` |
| BE | 2018 | 50th anniversary of May 1968 events in B | n/a | 181 | — | yolo+hough |  | `BE-2018-50th-anniversary-of-may-1968-e_022ff346.jpg` |
| AD | 2017 | Andorra – The Pyrenean country | n/a | 135 | — | yolo+hough |  | `AD-2017-andorra-the-pyrenean-country_7fdf4887.jpg` |
| AD | 2025 | Small states games | n/a | 116 | — | yolo+hough+polish |  | `AD-2025-small-states-games_32ed4d67.jpg` |
| AD | 2019 | 600 years since the constitution of the  | n/a | 117 | — | yolo+hough |  | `AD-2019-600-years-since-the-constituti_356ad2c5.jpg` |
| AT | 2016 | 200th anniversary of the founding of Aus | 0.87 | 127 | 145 | yolo+hough |  | `AT-2016-200th-anniversary-of-the-found_adf90393.jpg` |
| AD | 2020 | 27th Ibero-American Summit in Andorra | 0.88 | 129 | 146 | yolo+hough |  | `AD-2020-27th-ibero-american-summit-in-_36c55d31.jpg` |
| BE | 2008 | 60th anniversary of the Universal Declar | 0.89 | 196 | 219 | yolo+hough |  | `BE-2008-60th-anniversary-of-the-univer_f7d6df96.jpg` |
| BE | 2021 | 100 years since the signing of the Belgi | 0.93 | 127 | 136 | yolo+hough |  | `BE-2021-100-years-since-the-signing-of_dee38436.jpg` |
| AD | 2021 | Our Lady of Meritxell | 0.94 | 160 | 169 | yolo+hough+polish |  | `AD-2021-our-lady-of-meritxell_f5206173.jpg` |
| BE | 2009 | 200th birthday of Louis Braille | 0.99 | 87 | 87 | yolo+hough |  | `BE-2009-200th-birthday-of-louis-braill_6e56ac5a.jpg` |
| BE | 2021 | 500 years since the issuance of the Caro | 0.99 | 126 | 126 | yolo+hough |  | `BE-2021-500-years-since-the-issuance-o_ec8e8fb9.jpg` |
| AD | 2024 | 100 years of skiing in Andorra | 1.00 | 95 | 95 | yolo+hough |  | `AD-2024-100-years-of-skiing-in-andorra_2eb45709.jpg` |
| BE | 2011 | 1st Centenary of the International Women | 1.00 | 88 | 87 | yolo+hough |  | `BE-2011-1st-centenary-of-the-internati_7c76c475.jpg` |
| AD | 2019 | 2019 FIS Alpine Ski World Cup final | 1.09 | 189 | 173 | yolo+hough+polish |  | `AD-2019-2019-fis-alpine-ski-world-cup-_8aca66aa.jpg` |
