# info/ — 自习室座位索引

每个 `.txt` 对应一间自习室，文件名即自习室名称，内容是该室的座位号清单。
双校区（崇山 + 蒲河）共 21 间，覆盖书库、走廊、自习室与智慧空间等。

- 文件随打包产物一起分发，置于 app 同级，便于用户查看 / 校对座位号。
- `智慧空间.txt`、`三楼智慧研修空间.txt` 为 v5 新增。
- 在 GUI 里选定校区 / 自习室后，首选座位留空时程序会扫描对应室的全部座位兜底。

> 校区与自习室的下拉数据见 [`ui_qt/services/config_io.py`](../ui_qt/services/config_io.py)。
> 文件名含中文，git 默认会转义显示，可用 `git -c core.quotepath=false ls-files info` 查看原名。
