# IE27：三晚目标百分位与同票随机对照

5543列包括5541个库列和两个IE9锚。0、+1、+2分别描述，三晚汇总取算术平均；没有使用提前四晚作为正例。池外和缺失为中性0.5。随机在入场当晚抽一只票，同票跟随两晚，共20次。

| 夜晚 | 5543列同侧 | 5541库列同侧 | 随机同侧均值 | 随机最多 | 明显超出随机 | 同侧代表组 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 1209 | 1208 | 183.2 | 366 | True | 179 |
| +1 | 1299 | 1297 | 174.9 | 360 | True | 213 |
| +2 | 1138 | 1137 | 173.8 | 290 | True | 196 |
| 三晚平均 | 1431 | 1430 | 172.9 | 315 | True | 237 |

所有5543列、四种描述、各半年百分位/可用数/随机均值见[完整表](strong_continue_ie27_description_columns.tsv)。20次随机数量及完整分组保存在description.json。

按训练池行精确Spearman>0.7、短公式优先贪心去重，全六半年共1532组；正式留出每折重新分组和描述。以下仅展示稳定代表中分离最强的前12组，不据此增加候选。

## 0

| 代表 | 2024H1 | 2024H2 | 2025H1 | 2025H2 | 2026H1 | 2026H2 | 公式 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| force.value.20 | 0.781 | 0.734 | 0.819 | 0.627 | 0.626 | 0.735 | pool_pct(EMA((c-c[-1])*v,n)/mean(v*c,n)) |
| avwap.high.100 | 0.720 | 0.804 | 0.693 | 0.664 | 0.689 | 0.612 | pool_pct(c/VWAP since trailing-n highest high-1) |
| avwap.high.200__history250 | 0.740 | 0.808 | 0.740 | 0.611 | 0.654 | 0.731 | pool_pct(own_rank250(c/VWAP since trailing-n highest high-1)) |
| overlap.kama.10 | 0.834 | 0.827 | 0.881 | 0.616 | 0.606 | 0.678 | pool_pct(c/KAMA(n,fast=2,slow=30)-1) |
| elder.impulse.3__history250 | 0.721 | 0.663 | 0.705 | 0.603 | 0.603 | 0.639 | pool_pct(own_rank250(sign(EMA-EMA[-1])+sign(MACDhist-MACDhist[-1]))) |
| candles.longline.20__delta5 | 0.668 | 0.759 | 0.621 | 0.601 | 0.623 | 0.718 | pool_pct(pool_pct((B(white)-B(black))*B(long&(span>rng)))-pool_pct[-5]) |
| vcp.higher_low.10 | 0.597 | 0.769 | 0.683 | 0.606 | 0.672 | 0.726 | pool_pct(min(l,n)/min(l,2n)-1) |
| price_transform.div.14 | 0.791 | 0.808 | 0.626 | 0.627 | 0.592 | 0.807 | pool_pct(mean(c/o-1,n)) |
| smc.fvg_near.2 | 0.231 | 0.245 | 0.121 | 0.410 | 0.371 | 0.354 | pool_pct(negative distance to nearest live bullish gap / ATR20) |
| volatility.trange.50__history250 | 0.319 | 0.400 | 0.413 | 0.387 | 0.387 | 0.204 | pool_pct(own_rank250(mean(TR,n)/c)) |
| g1 | 0.825 | 0.830 | 0.940 | 0.624 | 0.619 | 0.586 | pool_pct(c/c[-1]-1) |
| overlap.tema.3__delta5 | 0.673 | 0.751 | 0.763 | 0.623 | 0.585 | 0.632 | pool_pct(pool_pct(c/(3*EMA-3*EMA2+EMA3)-1)-pool_pct[-5]) |

## +1

| 代表 | 2024H1 | 2024H2 | 2025H1 | 2025H2 | 2026H1 | 2026H2 | 公式 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| statistics.tsf.3__delta5 | 0.910 | 0.738 | 0.873 | 0.633 | 0.702 | 0.736 | pool_pct(pool_pct(linear_prediction(c,n,one_step)/c-1)-pool_pct[-5]) |
| volatility.trange.50__history250 | 0.314 | 0.298 | 0.372 | 0.371 | 0.365 | 0.170 | pool_pct(own_rank250(mean(TR,n)/c)) |
| overlap.sar.100 | 0.756 | 0.767 | 0.662 | 0.623 | 0.672 | 0.745 | pool_pct((c-PSAR(step=2/(n+1)*.1,max=.2))/c) |
| overlap.kama.10 | 0.824 | 0.794 | 0.792 | 0.603 | 0.668 | 0.640 | pool_pct(c/KAMA(n,fast=2,slow=30)-1) |
| statistics.linearreg.50 | 0.199 | 0.213 | 0.348 | 0.400 | 0.362 | 0.288 | pool_pct((LINEARREG(c,n)-c)/c) |
| price_transform.max.14__delta5 | 0.704 | 0.708 | 0.745 | 0.599 | 0.739 | 0.714 | pool_pct(pool_pct(c/max(c,n)-1)-pool_pct[-5]) |
| smc.resistance.5__delta5 | 0.828 | 0.783 | 0.877 | 0.618 | 0.598 | 0.666 | pool_pct(pool_pct(c/confirmed_high-1)-pool_pct[-5]) |
| volume.rvol.3 | 0.902 | 0.652 | 0.598 | 0.623 | 0.617 | 0.635 | pool_pct(v/mean(v,n)) |
| minervini.quality.50__delta5 | 0.630 | 0.712 | 0.612 | 0.597 | 0.611 | 0.651 | pool_pct(pool_pct(score*efficiency(c,n))-pool_pct[-5]) |
| force.value.20 | 0.768 | 0.743 | 0.803 | 0.597 | 0.663 | 0.657 | pool_pct(EMA((c-c[-1])*v,n)/mean(v*c,n)) |
| overlap.sarext.50 | 0.783 | 0.764 | 0.750 | 0.596 | 0.624 | 0.678 | pool_pct((c-PSAR(step=2/(n+1)*.2,max=.4))/c) |
| price_transform.max.100__delta5 | 0.845 | 0.656 | 0.621 | 0.595 | 0.708 | 0.677 | pool_pct(pool_pct(c/max(c,n)-1)-pool_pct[-5]) |

## +2

| 代表 | 2024H1 | 2024H2 | 2025H1 | 2025H2 | 2026H1 | 2026H2 | 公式 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| overlap.sar.100 | 0.806 | 0.762 | 0.746 | 0.657 | 0.668 | 0.765 | pool_pct((c-PSAR(step=2/(n+1)*.1,max=.2))/c) |
| smc.resistance.2__history250 | 0.834 | 0.700 | 0.730 | 0.608 | 0.637 | 0.671 | pool_pct(own_rank250(c/confirmed_high-1)) |
| price_transform.max.100__history250 | 0.658 | 0.779 | 0.608 | 0.607 | 0.652 | 0.787 | pool_pct(own_rank250(c/max(c,n)-1)) |
| overlap.kama.10 | 0.913 | 0.784 | 0.764 | 0.626 | 0.664 | 0.606 | pool_pct(c/KAMA(n,fast=2,slow=30)-1) |
| overlap.sarext.50 | 0.909 | 0.746 | 0.727 | 0.602 | 0.626 | 0.621 | pool_pct((c-PSAR(step=2/(n+1)*.2,max=.4))/c) |
| momentum.rocr.20 | 0.803 | 0.770 | 0.682 | 0.599 | 0.667 | 0.771 | pool_pct(c/c[-n]) |
| statistics.linearreg_intercept.10 | 0.130 | 0.271 | 0.227 | 0.403 | 0.370 | 0.351 | pool_pct(linear_intercept(c,n)/c-1) |
| statistics.linearreg.50 | 0.100 | 0.242 | 0.399 | 0.364 | 0.403 | 0.321 | pool_pct((LINEARREG(c,n)-c)/c) |
| avwap.high.200__history250 | 0.738 | 0.795 | 0.629 | 0.611 | 0.596 | 0.708 | pool_pct(own_rank250(c/VWAP since trailing-n highest high-1)) |
| overlap.sar.50__history250 | 0.816 | 0.792 | 0.629 | 0.599 | 0.595 | 0.777 | pool_pct(own_rank250((c-PSAR(step=2/(n+1)*.1,max=.2))/c)) |
| smc.resistance.5__delta5 | 0.880 | 0.771 | 0.796 | 0.614 | 0.607 | 0.593 | pool_pct(pool_pct(c/confirmed_high-1)-pool_pct[-5]) |
| volume.price_volume_corr.20 | 0.792 | 0.663 | 0.648 | 0.593 | 0.624 | 0.795 | pool_pct(corr(log(c/c[-1]),log(v/v[-1]),n)) |

## 三晚平均

| 代表 | 2024H1 | 2024H2 | 2025H1 | 2025H2 | 2026H1 | 2026H2 | 公式 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| overlap.sar.100 | 0.780 | 0.766 | 0.639 | 0.635 | 0.659 | 0.757 | pool_pct((c-PSAR(step=2/(n+1)*.1,max=.2))/c) |
| overlap.kama.10 | 0.857 | 0.802 | 0.812 | 0.615 | 0.646 | 0.641 | pool_pct(c/KAMA(n,fast=2,slow=30)-1) |
| volatility.trange.50__history250 | 0.380 | 0.321 | 0.388 | 0.372 | 0.379 | 0.180 | pool_pct(own_rank250(mean(TR,n)/c)) |
| force.value.20 | 0.797 | 0.734 | 0.802 | 0.611 | 0.651 | 0.660 | pool_pct(EMA((c-c[-1])*v,n)/mean(v*c,n)) |
| avwap.high.200__history250 | 0.737 | 0.780 | 0.687 | 0.604 | 0.632 | 0.728 | pool_pct(own_rank250(c/VWAP since trailing-n highest high-1)) |
| ichimoku.cloud.2__delta5 | 0.727 | 0.633 | 0.635 | 0.604 | 0.604 | 0.605 | pool_pct(pool_pct(c/max(spanA[-b],spanB[-b])-1)-pool_pct[-5]) |
| overlap.sarext.50 | 0.839 | 0.737 | 0.769 | 0.596 | 0.598 | 0.674 | pool_pct((c-PSAR(step=2/(n+1)*.2,max=.4))/c) |
| smc.resistance.5__delta5 | 0.826 | 0.746 | 0.770 | 0.602 | 0.594 | 0.632 | pool_pct(pool_pct(c/confirmed_high-1)-pool_pct[-5]) |
| price_transform.div.14 | 0.590 | 0.792 | 0.687 | 0.659 | 0.608 | 0.765 | pool_pct(mean(c/o-1,n)) |
| statistics.linearreg.50 | 0.159 | 0.231 | 0.384 | 0.384 | 0.410 | 0.285 | pool_pct((LINEARREG(c,n)-c)/c) |
| volume.price_volume_corr.20 | 0.778 | 0.666 | 0.644 | 0.587 | 0.633 | 0.807 | pool_pct(corr(log(c/c[-1]),log(v/v[-1]),n)) |
| near_ema9 | 0.231 | 0.281 | 0.367 | 0.417 | 0.388 | 0.418 | pool_pct(-abs(c/EMA(c,9)-1)/ADR20) |

## 与IE9当晚新挑三只成对比较

共345对，涉及41笔主目标；先晚内、再笔内、再半年等权，稳定代表259组。比较票来自IE9实际K=3、HOLD=10名单，目标本身剔除。

| 代表 | 2024H1差 | 2024H2差 | 2025H1差 | 2025H2差 | 2026H1差 | 2026H2差 | 2024H1胜率 | 2024H2胜率 | 2025H1胜率 | 2025H2胜率 | 2026H1胜率 | 2026H2胜率 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| near_ema9 | -0.511 | -0.602 | -0.396 | -0.401 | -0.377 | -0.314 | 0.067 | 0.044 | 0.222 | 0.083 | 0.218 | 0.167 |
| overlap.kama.10 | +0.494 | +0.507 | +0.538 | +0.349 | +0.274 | +0.307 | 0.944 | 0.933 | 0.917 | 0.854 | 0.774 | 0.852 |
| smc.resistance.2__history250 | +0.536 | +0.455 | +0.402 | +0.264 | +0.296 | +0.263 | 0.900 | 0.933 | 0.917 | 0.819 | 0.850 | 0.769 |
| statistics.linearreg_intercept.10 | -0.442 | -0.402 | -0.427 | -0.298 | -0.214 | -0.321 | 0.022 | 0.133 | 0.139 | 0.174 | 0.235 | 0.102 |
| price_transform.max.10 | +0.308 | +0.380 | +0.340 | +0.249 | +0.323 | +0.265 | 0.750 | 0.933 | 0.847 | 0.792 | 0.855 | 0.819 |
| force.value.20 | +0.323 | +0.418 | +0.456 | +0.312 | +0.276 | +0.336 | 0.833 | 0.867 | 0.944 | 0.812 | 0.761 | 0.750 |
| smc.resistance.5__delta5 | +0.504 | +0.420 | +0.456 | +0.247 | +0.226 | +0.218 | 0.956 | 0.889 | 0.861 | 0.750 | 0.752 | 0.796 |
| volatility.choppiness.3 | +0.616 | +0.532 | +0.383 | +0.336 | +0.350 | +0.250 | 0.978 | 0.933 | 0.889 | 0.889 | 0.838 | 0.750 |
| avwap.earnings.100__delta5 | +0.250 | +0.255 | +0.300 | +0.262 | +0.324 | +0.216 | 0.756 | 0.778 | 0.750 | 0.757 | 0.803 | 0.741 |
| smc.resistance.3 | +0.527 | +0.403 | +0.291 | +0.252 | +0.251 | +0.271 | 0.956 | 0.889 | 0.778 | 0.840 | 0.795 | 0.731 |
| overlap.sarext.50 | +0.365 | +0.500 | +0.410 | +0.299 | +0.234 | +0.331 | 0.844 | 0.911 | 0.861 | 0.743 | 0.731 | 0.806 |
| ichimoku.cloud.2__delta5 | +0.270 | +0.239 | +0.280 | +0.237 | +0.254 | +0.310 | 0.811 | 0.756 | 0.778 | 0.778 | 0.722 | 0.741 |
| overlap.sar.50__history250 | +0.328 | +0.523 | +0.212 | +0.210 | +0.188 | +0.533 | 0.844 | 0.956 | 0.722 | 0.715 | 0.722 | 0.917 |
| momentum.rocr.5 | +0.496 | +0.409 | +0.463 | +0.242 | +0.296 | +0.163 | 0.944 | 0.911 | 0.889 | 0.840 | 0.829 | 0.713 |
| momentum.plus_di.3__history250 | +0.566 | +0.384 | +0.478 | +0.257 | +0.310 | +0.183 | 0.978 | 0.911 | 0.903 | 0.868 | 0.799 | 0.713 |
| avwap.high.200__history250 | +0.292 | +0.427 | +0.218 | +0.164 | +0.232 | +0.408 | 0.778 | 0.878 | 0.722 | 0.708 | 0.752 | 0.796 |
| statistics.linearreg.50 | -0.371 | -0.478 | -0.270 | -0.391 | -0.192 | -0.293 | 0.078 | 0.044 | 0.250 | 0.097 | 0.295 | 0.250 |
| vortex.positive.3 | +0.145 | +0.284 | +0.343 | +0.176 | +0.278 | +0.185 | 0.756 | 0.867 | 0.778 | 0.701 | 0.735 | 0.787 |
| ichimoku.lagging.2__delta5 | +0.223 | +0.264 | +0.173 | +0.294 | +0.263 | +0.391 | 0.700 | 0.711 | 0.806 | 0.799 | 0.765 | 0.796 |
| avwap.earnings.100 | +0.253 | +0.390 | +0.339 | +0.241 | +0.266 | +0.321 | 0.700 | 0.867 | 0.778 | 0.729 | 0.778 | 0.806 |
