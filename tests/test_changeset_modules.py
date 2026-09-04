from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from changeset_modules import ItemModule, ModuleContext, ModuleRegistry


def change(
	file_name: str,
	sheet: str,
	key: str,
	after: dict[str, str],
	*,
	semantic_status: str = "eligible",
) -> dict[str, object]:
	return {
		"file_name": file_name,
		"repository_path": f"/repo/{file_name}",
		"sheet": sheet,
		"business_key": {"display": key},
		"change_type": "added",
		"revisions": [10],
		"before": None,
		"after": after,
		"changed_fields": list(after),
		"semantic_analysis": {"status": semantic_status},
	}


def skin_dtxml() -> str:
	return """<?xml version="1.0" encoding="utf-8"?>
<Root Schema="Skin">
  <Sheet Name="svr下发皮肤上下架表">
    <Columns><Column Name="ID" /><Column Name="英雄ID" /><Column Name="英雄名" /><Column Name="皮肤ID" /><Column Name="皮肤名称" /><Column Name="促销特卖1" /></Columns>
    <Row><Cell Name="ID">51015</Cell><Cell Name="英雄ID">510</Cell><Cell Name="英雄名">莉莉安</Cell><Cell Name="皮肤ID">15</Cell><Cell Name="皮肤名称">魔女回憶錄·幻之影</Cell><Cell Name="促销特卖1">510151</Cell><Cell Name="促销特卖2">510152</Cell></Row>
  </Sheet>
  <Sheet Name="皮肤促销特卖">
    <Columns><Column Name="促销特卖ID" /><Column Name="皮肤ID" /><Column Name="上架时间" /></Columns>
    <Row><Cell Name="促销特卖ID">510151</Cell><Cell Name="皮肤ID">51015</Cell><Cell Name="上架时间">20241031140000</Cell></Row>
  </Sheet>
  <Sheet Name="svr下发皮肤促销特卖">
    <Columns><Column Name="促销特卖ID" /><Column Name="皮肤ID" /><Column Name="是否可点券购买" /><Column Name="点券价格" /><Column Name="上架时间" /><Column Name="下架时间" /><Column Name="皮肤获取方式跳转入口" /></Columns>
    <Row><Cell Name="促销特卖ID">510152</Cell><Cell Name="皮肤ID">51015</Cell><Cell Name="是否可点券购买">否</Cell><Cell Name="点券价格">570</Cell><Cell Name="上架时间">20260811140000</Cell><Cell Name="下架时间">20260902235959</Cell><Cell Name="皮肤获取方式跳转入口">{&quot;Url&quot;:&quot;https://example.test/skin&quot;}</Cell></Row>
  </Sheet>
</Root>"""


def write_activity_impact_fixture(root: Path) -> None:
	path = root / "Xml" / "Garena" / "TW" / "CommonCore"
	path.mkdir(parents=True)
	(path / "日常活动表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="条件活动表"><Columns><Column Name="活动ID" /></Columns>
<Row><Cell Name="活动ID">200001441</Cell><Cell Name="活动名称">每日分享送奖励</Cell><Cell Name="活动入口">热更福利中心</Cell><Cell Name="是否每日刷新">是</Cell><Cell Name="团队类型">活动团队_单人</Cell><Cell Name="条件1简介">每日分享1次</Cell><Cell Name="条件1类型">活动_通用条件</Cell><Cell Name="条件1目标值">1</Cell><Cell Name="条件1参数1">21</Cell><Cell Name="条件1奖励ID">1001</Cell><Cell Name="条件1是否每日刷新">否</Cell><Cell Name="条件1跳转入口">{&quot;name&quot;:&quot;OpenForm&quot;,&quot;Form&quot;:4}</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "35.svr下发随机奖励配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="随机奖励配置表"><Columns><Column Name="随机奖励ID" /></Columns>
<Row><Cell Name="随机奖励ID">1001</Cell><Cell Name="随机奖励描述">分享奖励</Cell><Cell Name="奖励1类型">随机道具</Cell><Cell Name="奖励1ID">5001</Cell><Cell Name="奖励1数量下限">10</Cell><Cell Name="奖励1数量上限">10</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "41.svr下发道具信息表_Syndra.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="道具信息"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">5001</Cell><Cell Name="名称">分享币</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
def write_item_business_fixture(root: Path, *, limited_hours: str = "240") -> None:
	path = root / "Xml" / "Garena" / "TW" / "CommonCore"
	path.mkdir(parents=True)
	(path / "日常活动表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="条件活动表"><Columns><Column Name="活动ID" /></Columns>
<Row><Cell Name="活动ID">600</Cell><Cell Name="活动名称">收集纪念币</Cell><Cell Name="开始时间">20260801000000</Cell><Cell Name="结束时间">20260807235959</Cell><Cell Name="条件1简介">完成对局</Cell><Cell Name="条件1奖励ID">1001</Cell><Cell Name="条件2简介">参与两局</Cell><Cell Name="条件2奖励ID">1001</Cell></Row>
<Row><Cell Name="活动ID">603</Cell><Cell Name="活动名称">纪念币累计进度</Cell><Cell Name="开始时间">20260801000000</Cell><Cell Name="结束时间">20260807235959</Cell><Cell Name="条件1简介">进度1</Cell><Cell Name="条件1类型">活动_通用条件</Cell><Cell Name="条件1目标值">3</Cell><Cell Name="条件1参数1">900</Cell><Cell Name="条件1奖励ID">1002</Cell><Cell Name="条件1是否每日刷新">否</Cell><Cell Name="条件2简介">进度2</Cell><Cell Name="条件2类型">活动_通用条件</Cell><Cell Name="条件2目标值">7</Cell><Cell Name="条件2参数1">900</Cell><Cell Name="条件2奖励ID">1002</Cell><Cell Name="条件2是否每日刷新">否</Cell></Row>
</Sheet>
<Sheet Name="兑换活动表"><Columns><Column Name="活动ID" /></Columns>
<Row><Cell Name="活动ID">601</Cell><Cell Name="活动索引">1</Cell><Cell Name="活动名称">纪念币兑换奖励</Cell><Cell Name="开始时间">20260801000000</Cell><Cell Name="结束时间">20260807235959</Cell><Cell Name="兑换产出物品类型">道具</Cell><Cell Name="兑换产出物品ID">5002</Cell><Cell Name="兑换收集物品1类型">道具</Cell><Cell Name="兑换收集物品1ID">5001</Cell></Row>
</Sheet>
<Sheet Name="收集兑换活动表"><Columns><Column Name="活动ID" /></Columns>
<Row><Cell Name="活动ID">602</Cell><Cell Name="活动名称">夏日纪念币收集活动</Cell><Cell Name="开始时间">20260801000000</Cell><Cell Name="结束时间">20260807235959</Cell><Cell Name="条件活动ID">600</Cell><Cell Name="兑换活动ID">601</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "159.通用条件配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="通用条件配置表"><Columns><Column Name="条件id" /></Columns>
<Row><Cell Name="条件id">900</Cell><Cell Name="条件简介">持有纪念币</Cell><Cell Name="条件类型">通用条件_拥有指定物品达到指定数量</Cell><Cell Name="参数1">2</Cell><Cell Name="参数2">5001</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "157.ilua热更活动聚合配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="ilua聚合配置表"><Columns><Column Name="活动ID" /></Columns>
<Row><Cell Name="活动ID">700</Cell><Cell Name="活动名称">夏日纪念币聚合活动</Cell><Cell Name="开始时间">20260801000000</Cell><Cell Name="结束时间">20260807235959</Cell><Cell Name="活动详情的json串">{"configType":"SummerCollectCfg","tokenID":5001,"leiJiActID":603,"ruleID":88}</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "35.svr下发随机奖励配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="随机奖励配置表"><Columns><Column Name="随机奖励ID" /></Columns>
<Row><Cell Name="随机奖励ID">1001</Cell><Cell Name="奖励1类型">随机道具</Cell><Cell Name="奖励1ID">5001</Cell><Cell Name="奖励1数量下限">1</Cell><Cell Name="奖励1数量上限">1</Cell></Row>
<Row><Cell Name="随机奖励ID">1002</Cell><Cell Name="奖励1类型">随机钻石</Cell><Cell Name="奖励1数量下限">20</Cell><Cell Name="奖励1数量上限">20</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "41.svr下发道具信息表_Syndra.dtxml").write_text(
		f"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="道具信息"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">5001</Cell><Cell Name="名称">夏日纪念币</Cell><Cell Name="类型">普通道具</Cell><Cell Name="品质">随意填写</Cell><Cell Name="描述">活动兑换材料</Cell><Cell Name="限时道具有效期">{limited_hours}</Cell></Row>
<Row><Cell Name="ID">5002</Cell><Cell Name="名称">钻石礼包</Cell><Cell Name="类型">礼包道具</Cell><Cell Name="效果参数1">1002</Cell></Row>
<Row><Cell Name="ID">5003</Cell><Cell Name="名称">自选礼包</Cell><Cell Name="类型">延后领用礼包</Cell><Cell Name="效果参数1">9001</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "【运营配置】局内交流配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="svr预定义文本"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">412</Cell><Cell Name="显示类型">信号面板</Cell><Cell Name="文本内容">耶 怎么样啊?</Cell><Cell Name="所属频道标题">交流</Cell><Cell Name="所属频道ID">1</Cell><Cell Name="快捷消息主题ID">38</Cell><Cell Name="快捷消息条目ID">1</Cell></Row>
</Sheet>
<Sheet Name="svr快捷消息主题配置"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">38</Cell><Cell Name="开始时间">20260801000000</Cell><Cell Name="结束时间">20260831235959</Cell><Cell Name="主题名称">胆大党</Cell></Row>
</Sheet>
</Root>""",
		encoding="utf-8",
	)
	(path / "140.延后领取礼包配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="服务器下发延后领取礼包配置表"><Columns><Column Name="延后领取礼包ID" /></Columns>
<Row><Cell Name="延后领取礼包ID">9001</Cell><Cell Name="延后领取礼包描述">二选一礼包</Cell><Cell Name="可选个数">1</Cell><Cell Name="奖励1类型">随机钻石</Cell><Cell Name="奖励1数量">20</Cell><Cell Name="奖励2类型">随机金币</Cell><Cell Name="奖励2数量">100</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)


def write_item_source_priority_fixture(root: Path) -> None:
	path = root / "Xml" / "Garena" / "TW" / "CommonCore"
	path.mkdir(parents=True)
	(path / "【运营配置】41.道具信息表_Syndra.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="道具信息"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">9001</Cell><Cell Name="名称">客户端主表道具</Cell><Cell Name="类型">普通道具</Cell></Row>
</Sheet>
<Sheet Name="道具信息增量"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">9001</Cell><Cell Name="名称">客户端增量道具</Cell><Cell Name="类型">礼包道具</Cell><Cell Name="效果参数1">1001</Cell></Row>
<Row><Cell Name="ID">9002</Cell><Cell Name="名称">仅增量道具</Cell><Cell Name="类型">快捷消息</Cell><Cell Name="效果参数1">412</Cell></Row>
<Row><Cell Name="ID">9003</Cell><Cell Name="名称">头像解锁道具</Cell><Cell Name="类型">头像道具</Cell><Cell Name="效果参数1">741</Cell></Row>
<Row><Cell Name="ID">9004</Cell><Cell Name="名称">头像框解锁道具</Cell><Cell Name="类型">头像框资源</Cell><Cell Name="效果参数1">1008</Cell></Row>
<Row><Cell Name="ID">9005</Cell><Cell Name="名称">限时单局表情</Cell><Cell Name="类型">单局特效</Cell><Cell Name="效果参数1">10</Cell><Cell Name="效果参数2">41612</Cell><Cell Name="效果参数3">1</Cell></Row>
<Row><Cell Name="ID">9006</Cell><Cell Name="名称">高速婆婆头套</Cell><Cell Name="类型">次元部件道具</Cell><Cell Name="效果参数1">区分男女性别</Cell><Cell Name="效果参数2">61007009</Cell><Cell Name="效果参数3">62007009</Cell></Row>
<Row><Cell Name="ID">9007</Cell><Cell Name="名称">传说高校</Cell><Cell Name="类型">次元主题道具</Cell><Cell Name="效果参数1">区分男女性别</Cell><Cell Name="效果参数2">7007</Cell><Cell Name="效果参数3">7008</Cell></Row>
<Row><Cell Name="ID">9011</Cell><Cell Name="名称">限时点券500</Cell><Cell Name="类型">限定点券</Cell><Cell Name="效果参数1">500</Cell></Row>
<Row><Cell Name="ID">9014</Cell><Cell Name="名称">指定皮肤八折券</Cell><Cell Name="类型">折扣券</Cell><Cell Name="效果参数1">80</Cell><Cell Name="效果参数2">抵扣类型_指定皮肤</Cell><Cell Name="效果参数3">1085</Cell><Cell Name="可使用开始日期">20260306000000</Cell><Cell Name="可使用结束日期">20260410235959</Cell></Row>
<Row><Cell Name="ID">9015</Cell><Cell Name="名称">满175减50皮肤券</Cell><Cell Name="类型">满减抵价券</Cell><Cell Name="效果参数1">50</Cell><Cell Name="效果参数2">抵扣类型_皮肤</Cell><Cell Name="效果参数4">175</Cell><Cell Name="限时道具有效期">168</Cell></Row>
<Row><Cell Name="ID">9016</Cell><Cell Name="名称">三选一礼包</Cell><Cell Name="类型">预选礼包</Cell><Cell Name="效果参数1">893</Cell><Cell Name="效果参数2">2</Cell></Row>
<Row><Cell Name="ID">9017</Cell><Cell Name="名称">樱吹雪12小时体验卡</Cell><Cell Name="类型">体验卡</Cell><Cell Name="效果参数1">皮肤体验卡</Cell><Cell Name="效果参数2">10618</Cell><Cell Name="效果参数3">1</Cell><Cell Name="小时体验卡时间">12</Cell><Cell Name="使用获取的钻石数量">5</Cell><Cell Name="可自动转换道具ID">9010</Cell><Cell Name="可自动转换道具数量">12</Cell></Row>
<Row><Cell Name="ID">9018</Cell><Cell Name="名称">测试魔法水晶</Cell><Cell Name="类型">夺宝抽奖券</Cell></Row>
<Row><Cell Name="ID">9019</Cell><Cell Name="名称">测试小喇叭</Cell><Cell Name="类型">喇叭道具</Cell><Cell Name="效果参数1">10041</Cell><Cell Name="效果参数2">1</Cell></Row>
<Row><Cell Name="ID">9020</Cell><Cell Name="名称">测试战败加星卡</Cell><Cell Name="类型">排位守护卡</Cell><Cell Name="效果参数1">失败加星</Cell><Cell Name="效果参数2">27</Cell><Cell Name="限时道具有效期">168</Cell><Cell Name="可使用开始日期">20260801000000</Cell><Cell Name="可使用结束日期">20260831235959</Cell></Row>
<Row><Cell Name="ID">9021</Cell><Cell Name="名称">测试系统语音道具</Cell><Cell Name="类型">系统语音</Cell><Cell Name="效果参数1">8</Cell></Row>
<Row><Cell Name="ID">9022</Cell><Cell Name="名称">测试隐藏活动Token</Cell><Cell Name="类型">普通道具</Cell><Cell Name="是否是隐藏道具">1</Cell></Row>
<Row><Cell Name="ID">9023</Cell><Cell Name="名称">测试限量礼包</Cell><Cell Name="类型">礼包道具</Cell><Cell Name="效果参数1">2002</Cell></Row>
</Sheet>
<Sheet Name="喇叭信息"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">10041</Cell><Cell Name="喇叭类型">小喇叭</Cell><Cell Name="字数限制">30</Cell><Cell Name="最小显示时间">3</Cell><Cell Name="最大显示时间">10</Cell></Row>
<Row><Cell Name="ID">10046</Cell><Cell Name="喇叭类型">大喇叭</Cell><Cell Name="最小显示时间">10</Cell><Cell Name="最大显示时间">30</Cell><Cell Name="背景资源路径">jmd</Cell><Cell Name="特效资源路径">UI_FriendRelationGiveGift_DrtRose</Cell><Cell Name="图标资源路径">YingYuanBang</Cell><Cell Name="描述">HiFive！我们传说对决</Cell></Row>
</Sheet>
<Sheet Name="英雄皮肤组"><Columns><Column Name="参数ID" /></Columns>
<Row><Cell Name="参数ID">1085</Cell><Cell Name="参数1">10618</Cell></Row>
</Sheet>
</Root>""",
		encoding="utf-8",
	)
	(path / "41.svr下发道具信息表_Syndra.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="道具信息"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">9001</Cell><Cell Name="名称">服务器生效道具</Cell><Cell Name="类型">头像框资源</Cell><Cell Name="效果参数1">88</Cell></Row>
<Row><Cell Name="ID">9008</Cell><Cell Name="名称">第92篇章贡献值(50点)</Cell><Cell Name="类型">VALORPASS积分卡</Cell><Cell Name="效果参数1">2001</Cell><Cell Name="效果参数2">92</Cell></Row>
<Row><Cell Name="ID">9009</Cell><Cell Name="名称">第92篇章精英圣典</Cell><Cell Name="类型">VP通行证</Cell><Cell Name="效果参数1">2</Cell><Cell Name="效果参数2">92</Cell></Row>
<Row><Cell Name="ID">9010</Cell><Cell Name="名称">都市传说币</Cell><Cell Name="类型">小应用云积分</Cell><Cell Name="效果参数1">324601</Cell></Row>
<Row><Cell Name="ID">9012</Cell><Cell Name="名称">惊喜宝箱</Cell><Cell Name="类型">活动抽奖礼包</Cell><Cell Name="效果参数1">10</Cell><Cell Name="效果参数2">0</Cell></Row>
<Row><Cell Name="ID">9013</Cell><Cell Name="名称">超自然现象杂志</Cell><Cell Name="类型">亲密度礼物</Cell><Cell Name="描述">赠送后双方增加15点亲密度</Cell><Cell Name="效果参数1">10046</Cell><Cell Name="效果参数2">特殊亲密度道具</Cell><Cell Name="效果参数3">15</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "35.svr下发随机奖励配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="随机奖励配置表"><Columns><Column Name="随机奖励ID" /></Columns>
<Row><Cell Name="随机奖励ID">2001</Cell><Cell Name="随机奖励描述">50圣典积分奖励</Cell><Cell Name="奖励1类型">随机VALORPASS积分</Cell><Cell Name="奖励1数量下限">50</Cell><Cell Name="奖励1数量上限">50</Cell></Row>
<Row><Cell Name="随机奖励ID">2002</Cell><Cell Name="随机奖励描述">都市传说币奖励</Cell><Cell Name="奖励1类型">随机道具</Cell><Cell Name="奖励1ID">9010</Cell><Cell Name="奖励1数量下限">300</Cell><Cell Name="奖励1数量上限">300</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "48.礼包产出控制表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="礼包产出控制"><Columns><Column Name="随机奖励ID" /></Columns>
<Row><Cell Name="随机奖励ID">2002</Cell><Cell Name="指定物品1每日上限">10</Cell><Cell Name="指定物品1总上限">100</Cell><Cell Name="指定物品1控制间隔">3600</Cell><Cell Name="指定物品1控制间隔产出上限">3</Cell></Row>
</Sheet>
<Sheet Name="礼包产出控制新"><Columns><Column Name="随机奖励ID" /></Columns></Sheet>
</Root>""",
		encoding="utf-8",
	)
	(path / "活动抽奖表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="基础信息"><Columns><Column Name="批次ID" /></Columns></Sheet>
<Sheet Name="奖励池"><Columns><Column Name="奖励池ID" /></Columns>
<Row><Cell Name="奖励池ID">1200</Cell><Cell Name="奖励序号">1</Cell><Cell Name="奖励ID">2002</Cell><Cell Name="权重">100</Cell><Cell Name="奖励等级">客户端区间奖励</Cell></Row>
</Sheet>
<Sheet Name="svr下发基础信息"><Columns><Column Name="批次ID" /></Columns>
<Row><Cell Name="批次ID">10</Cell><Cell Name="规则ID">1</Cell><Cell Name="主奖池ID">1100</Cell><Cell Name="是否开启主奖池去重">0</Cell><Cell Name="保底1类型">1</Cell><Cell Name="保底1必得抽数">15</Cell><Cell Name="保底1开启去重">1</Cell><Cell Name="保底1奖励池ID">1101</Cell><Cell Name="保底1是否循环保底">1</Cell><Cell Name="区间1抽数">20</Cell><Cell Name="区间1奖励池ID">1200</Cell></Row>
</Sheet>
<Sheet Name="svr下发奖励池"><Columns><Column Name="奖励池ID" /></Columns>
<Row><Cell Name="奖励池ID">1100</Cell><Cell Name="奖励序号">1</Cell><Cell Name="奖励ID">2001</Cell><Cell Name="权重">1</Cell><Cell Name="奖励等级">稀有奖励</Cell></Row>
<Row><Cell Name="奖励池ID">1100</Cell><Cell Name="奖励序号">2</Cell><Cell Name="奖励ID">2002</Cell><Cell Name="权重">99</Cell><Cell Name="奖励等级">普通奖励</Cell></Row>
<Row><Cell Name="奖励池ID">1101</Cell><Cell Name="奖励序号">1</Cell><Cell Name="奖励ID">2001</Cell><Cell Name="权重">1</Cell><Cell Name="奖励等级">保底奖励</Cell></Row>
</Sheet>
</Root>""",
		encoding="utf-8",
	)
	(path / "119.ValorPass系统配置.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="赛季表"><Columns><Column Name="赛季ID" /></Columns>
<Row><Cell Name="赛季ID">92</Cell><Cell Name="赛季开始时间">20260801000000</Cell><Cell Name="赛季结束时间">20260831235959</Cell><Cell Name="赛季标题CDN">valorpass_title_vp92.png</Cell></Row>
</Sheet>
<Sheet Name="解锁表"><Columns><Column Name="赛季ID" /></Columns>
<Row><Cell Name="赛季ID">92</Cell><Cell Name="精英通行证货币类型">点券</Cell><Cell Name="精英通行证原价">3650</Cell><Cell Name="精英通行证折后价">710</Cell></Row>
</Sheet>
<Sheet Name="svr下发解锁表"><Columns><Column Name="赛季ID" /></Columns>
<Row><Cell Name="赛季ID">92</Cell><Cell Name="精英通行证道具ID">9009</Cell><Cell Name="精英通行证货币类型">点券</Cell><Cell Name="精英通行证原价">3650</Cell><Cell Name="精英通行证折后价">699</Cell></Row>
</Sheet>
</Root>""",
		encoding="utf-8",
	)
	(path / "【运营配置】限定点券批次表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="限定点券批次表"><Columns><Column Name="批次ID" /></Columns>
<Row><Cell Name="批次ID">7</Cell><Cell Name="开始时间">20260708000000</Cell><Cell Name="结束时间">20260816235959</Cell></Row>
<Row><Cell Name="批次ID">8</Cell><Cell Name="开始时间">20260817000000</Cell><Cell Name="结束时间">20261231235959</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "【运营配置】73.皮肤配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="皮肤配置表"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">10618</Cell><Cell Name="皮肤名称">克里希·樱吹雪</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "【运营配置】142.局内动作配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="局内动作上下架表"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">5100001</Cell><Cell Name="名称">莉莉安的舞蹈</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "预选择配置.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="预选择"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">893</Cell><Cell Name="选项1类型">预选择物品</Cell><Cell Name="选项1ID">495</Cell><Cell Name="选项1展示排序">1</Cell><Cell Name="选项2类型">预选择物品</Cell><Cell Name="选项2ID">496</Cell><Cell Name="选项2展示排序">2</Cell><Cell Name="选项3类型">预选择物品</Cell><Cell Name="选项3ID">497</Cell><Cell Name="选项3展示排序">3</Cell></Row>
</Sheet>
<Sheet Name="预选择物品"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">495</Cell><Cell Name="物品类型">英雄皮肤</Cell><Cell Name="物品ID">10618</Cell><Cell Name="物品数量">1</Cell></Row>
<Row><Cell Name="ID">496</Cell><Cell Name="物品类型">道具</Cell><Cell Name="物品ID">9010</Cell><Cell Name="物品数量">300</Cell></Row>
<Row><Cell Name="ID">497</Cell><Cell Name="物品类型">局内动作</Cell><Cell Name="物品ID">5100001</Cell><Cell Name="物品数量">1</Cell></Row>
</Sheet>
</Root>""",
		encoding="utf-8",
	)
	(path / "幸运夺宝表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="夺宝配置"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">1087</Cell><Cell Name="夺宝标签">夺宝标签_普通</Cell><Cell Name="开始时间">20260801000000</Cell><Cell Name="结束时间">20260831235959</Cell><Cell Name="是否开启">是</Cell><Cell Name="[抽奖类型]1类型">单抽</Cell><Cell Name="[抽奖类型]1消耗道具ID">9018</Cell><Cell Name="[抽奖类型]1消耗道具个数">1</Cell><Cell Name="[抽奖类型]2类型">五连抽</Cell><Cell Name="[抽奖类型]2消耗道具ID">9018</Cell><Cell Name="[抽奖类型]2消耗道具个数">5</Cell><Cell Name="抽中稀有物品最少次数">1</Cell><Cell Name="抽中稀有物品最大次数">200</Cell></Row>
</Sheet>
<Sheet Name="奖池批次"><Columns><Column Name="夺宝ID" /></Columns>
<Row><Cell Name="夺宝ID">1087</Cell><Cell Name="奖池ID">286</Cell><Cell Name="开始时间">20260801000000</Cell><Cell Name="结束时间">20260831235959</Cell></Row>
</Sheet>
<Sheet Name="奖励池设定"><Columns><Column Name="奖励池ID" /></Columns>
<Row><Cell Name="奖励池ID">286</Cell><Cell Name="奖励序号">1</Cell><Cell Name="物品类型">随机皮肤</Cell><Cell Name="物品ID">10618</Cell><Cell Name="物品数量">1</Cell><Cell Name="物品概率">100</Cell><Cell Name="大奖品级ID">2</Cell></Row>
<Row><Cell Name="奖励池ID">286</Cell><Cell Name="奖励序号">2</Cell><Cell Name="物品类型">随机钻石</Cell><Cell Name="物品数量">60</Cell><Cell Name="物品概率">9900</Cell><Cell Name="大奖品级ID">1</Cell></Row>
</Sheet>
</Root>""",
		encoding="utf-8",
	)
	(path / "97.莉莉安魔法抽奖表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="抽奖上架表"><Columns><Column Name="抽奖ID" /></Columns>
<Row><Cell Name="抽奖ID">10001</Cell><Cell Name="抽奖类型">高级奖池</Cell><Cell Name="开始时间">20260801000000</Cell><Cell Name="结束时间">20260831235959</Cell><Cell Name="活动名字">测试活动抽奖</Cell><Cell Name="货币消耗类型">9018</Cell><Cell Name="货币消耗值">1</Cell><Cell Name="奖励池ID">292</Cell><Cell Name="连抽数量">5</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "【运营配置】局内交流配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="svr预定义文本"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">412</Cell><Cell Name="显示类型">信号面板</Cell><Cell Name="文本内容">耶 怎么样啊?</Cell><Cell Name="所属频道标题">交流</Cell><Cell Name="所属频道ID">1</Cell><Cell Name="快捷消息主题ID">38</Cell><Cell Name="快捷消息条目ID">1</Cell></Row>
</Sheet>
<Sheet Name="svr快捷消息主题配置"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">38</Cell><Cell Name="开始时间">20260801000000</Cell><Cell Name="结束时间">20260831235959</Cell><Cell Name="主题名称">胆大党</Cell></Row>
</Sheet>
<Sheet Name="系统语音配置"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">8</Cell><Cell Name="标题">客户端林襄语音</Cell><Cell Name="CV">CV:客户端</Cell><Cell Name="结束时间">20260930235959</Cell><Cell Name="DLC类型名">ClientVoice</Cell><Cell Name="Bank资源">ClientBank</Cell></Row>
</Sheet>
<Sheet Name="svr系统语音配置"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">8</Cell><Cell Name="标题">超香的林襄语音</Cell><Cell Name="副标题">啦啦队女神为你加油</Cell><Cell Name="CV">CV:林襄</Cell><Cell Name="开始时间">20260801000000</Cell><Cell Name="结束时间">20260831235959</Cell><Cell Name="DLC类型名">BattleSystemVoiceTWLinXiang</Cell><Cell Name="Bank资源">TW_LinXiang_1</Cell><Cell Name="是否关闭">1</Cell><Cell Name="试听1标题">传说对决，真香！</Cell><Cell Name="试听1事件">Play_5V5_sys_1_01</Cell></Row>
</Sheet>
</Root>""",
		encoding="utf-8",
	)
	(path / "【运营配置】玩家头像信息表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="玩家头像信息"><Columns><Column Name="头像ID" /></Columns>
<Row><Cell Name="头像ID">741</Cell><Cell Name="头像名称">客户端头像名称</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "玩家头像信息表svr下发.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="玩家头像信息"><Columns><Column Name="头像ID" /></Columns>
<Row><Cell Name="头像ID">741</Cell><Cell Name="头像名称">高速婆婆头像</Cell><Cell Name="头像图标">valorpass741.png</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "【运营配置】头像框信息表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="头像框信息表"><Columns><Column Name="头像框ID" /></Columns>
<Row><Cell Name="头像框ID">1008</Cell><Cell Name="头像框描述">客户端头像框</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "头像框信息表增量下发.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="头像框信息表"><Columns><Column Name="头像框ID" /></Columns>
<Row><Cell Name="头像框ID">1008</Cell><Cell Name="头像框描述">高速婆婆相框</Cell><Cell Name="头像框图标">HeadFrame1008.png</Cell><Cell Name="显示开始时间">20260801000000</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	base_path = root / "Xml" / "CommonCore"
	base_path.mkdir(parents=True)
	(base_path / "88.【研发配置】局内特效配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="局内特效配置表"><Columns><Column Name="特效ID" /></Columns>
<Row><Cell Name="特效ID">41612</Cell><Cell Name="特效类型">单局表情</Cell><Cell Name="特效名称">基础表情名称</Cell><Cell Name="特效描述">基础表情描述</Cell><Cell Name="英雄适用范围">全体适用</Cell><Cell Name="模式适用范围">全模式通用</Cell><Cell Name="资源文件">Prefab/Emoji_41612</Cell><Cell Name="是否进包">1</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(base_path / "次元部件表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="次元部件表"><Columns><Column Name="部件ID" /></Columns>
<Row><Cell Name="部件ID">61007009</Cell><Cell Name="性别">1</Cell><Cell Name="类型">6</Cell><Cell Name="名称">高速婆婆</Cell><Cell Name="图标">61007009.png</Cell><Cell Name="映射性转id">62007009</Cell><Cell Name="投放ID">30119</Cell></Row>
<Row><Cell Name="部件ID">62007009</Cell><Cell Name="性别">2</Cell><Cell Name="类型">6</Cell><Cell Name="名称">高速婆婆</Cell><Cell Name="图标">62007009.png</Cell><Cell Name="映射性转id">61007009</Cell><Cell Name="投放ID">30119</Cell></Row>
<Row><Cell Name="部件ID">31007003</Cell><Cell Name="性别">1</Cell><Cell Name="类型">3</Cell><Cell Name="名称">男款高校上衣</Cell></Row>
<Row><Cell Name="部件ID">41007003</Cell><Cell Name="性别">1</Cell><Cell Name="类型">4</Cell><Cell Name="名称">男款高校下装</Cell></Row>
<Row><Cell Name="部件ID">32007003</Cell><Cell Name="性别">2</Cell><Cell Name="类型">3</Cell><Cell Name="名称">女款高校上衣</Cell></Row>
<Row><Cell Name="部件ID">42007003</Cell><Cell Name="性别">2</Cell><Cell Name="类型">4</Cell><Cell Name="名称">女款高校下装</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(base_path / "次元配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="次元主题表"><Columns><Column Name="搭配ID" /></Columns>
<Row><Cell Name="搭配ID">7007</Cell><Cell Name="性别">1</Cell><Cell Name="名称">恰少年·灼意</Cell><Cell Name="部件1">31007003</Cell><Cell Name="部件2">41007003</Cell><Cell Name="性转主题ID">7008</Cell><Cell Name="投放ID">40014</Cell></Row>
<Row><Cell Name="搭配ID">7008</Cell><Cell Name="性别">2</Cell><Cell Name="名称">恰少年·灼意</Cell><Cell Name="部件1">32007003</Cell><Cell Name="部件2">42007003</Cell><Cell Name="性转主题ID">7007</Cell><Cell Name="投放ID">40014</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "【运营配置】88.局内特效配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="局内特效配置表"><Columns><Column Name="特效ID" /></Columns>
<Row><Cell Name="特效ID">41612</Cell><Cell Name="特效名称">客户端表情名称</Cell></Row>
</Sheet>
<Sheet Name="svr局内特效配置表"><Columns><Column Name="特效ID" /></Columns>
<Row><Cell Name="特效ID">41612</Cell><Cell Name="特效名称">服务器表情名称</Cell></Row>
</Sheet>
</Root>""",
		encoding="utf-8",
	)
	(path / "89.局内特效上下架与促销表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="局内特效上下架表"><Columns><Column Name="局内特效ID" /></Columns>
<Row><Cell Name="局内特效ID">41612</Cell><Cell Name="特效名称">客户端上架名称</Cell><Cell Name="上架时间">20270501000000</Cell><Cell Name="是否可购买">0</Cell></Row>
</Sheet>
<Sheet Name="svr局内特效上下架表"><Columns><Column Name="局内特效ID" /></Columns>
<Row><Cell Name="局内特效ID">41612</Cell><Cell Name="特效名称">給你0分</Cell><Cell Name="上架时间">20260725100000</Cell><Cell Name="是否可购买">0</Cell><Cell Name="购买货币类型">点券</Cell><Cell Name="价格">99</Cell></Row>
</Sheet>
</Root>""",
		encoding="utf-8",
	)
	(path / "【运营配置】次元上下架与促销表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="次元部件上下架表"><Columns><Column Name="次元部件或主题ID" /></Columns>
<Row><Cell Name="次元部件或主题ID">61007009</Cell><Cell Name="名称">客户端男部件</Cell><Cell Name="上架时间">20270501000000</Cell><Cell Name="是否可购买">否</Cell></Row>
<Row><Cell Name="次元部件或主题ID">62007009</Cell><Cell Name="名称">客户端女部件</Cell><Cell Name="上架时间">20270501000000</Cell><Cell Name="是否可购买">否</Cell></Row>
<Row><Cell Name="次元部件或主题ID">7007</Cell><Cell Name="是否是主题">1</Cell><Cell Name="名称">客户端男主题</Cell><Cell Name="上架时间">20270501000000</Cell><Cell Name="是否可购买">否</Cell></Row>
<Row><Cell Name="次元部件或主题ID">7008</Cell><Cell Name="是否是主题">1</Cell><Cell Name="名称">客户端女主题</Cell><Cell Name="上架时间">20270501000000</Cell><Cell Name="是否可购买">否</Cell></Row>
</Sheet>
<Sheet Name="svr次元部件上下架表"><Columns><Column Name="次元部件或主题ID" /></Columns>
<Row><Cell Name="次元部件或主题ID">61007009</Cell><Cell Name="名称">高速婆婆男款</Cell><Cell Name="上架时间">20260723000000</Cell><Cell Name="是否可购买">否</Cell></Row>
<Row><Cell Name="次元部件或主题ID">62007009</Cell><Cell Name="名称">高速婆婆女款</Cell><Cell Name="上架时间">20260723000000</Cell><Cell Name="是否可购买">否</Cell></Row>
<Row><Cell Name="次元部件或主题ID">7007</Cell><Cell Name="是否是主题">1</Cell><Cell Name="名称">服务器男主题</Cell><Cell Name="上架时间">20261217000000</Cell><Cell Name="是否可购买">否</Cell></Row>
<Row><Cell Name="次元部件或主题ID">7008</Cell><Cell Name="是否是主题">1</Cell><Cell Name="名称">服务器女主题</Cell><Cell Name="上架时间">20261217000000</Cell><Cell Name="是否可购买">否</Cell></Row>
</Sheet>
</Root>""",
		encoding="utf-8",
	)


def write_exchange_fixture(root: Path) -> None:
	path = root / "Xml" / "Garena" / "TW" / "CommonCore"
	path.mkdir(parents=True)
	(path / "日常活动表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="兑换活动表"><Columns><Column Name="活动ID" /><Column Name="活动索引" /></Columns>
<Row><Cell Name="序号id">30001</Cell><Cell Name="活动ID">300</Cell><Cell Name="活动索引">1</Cell><Cell Name="活动名称">材料兑换</Cell><Cell Name="活动入口">热更福利中心</Cell><Cell Name="兑换次数是否日清">否</Cell><Cell Name="重复兑换次数">5</Cell><Cell Name="兑换收集物品1类型">道具</Cell><Cell Name="兑换收集物品1ID">7001</Cell><Cell Name="兑换收集物品1数量">10</Cell><Cell Name="兑换产出物品类型">道具</Cell><Cell Name="兑换产出物品ID">8001</Cell><Cell Name="兑换产出物品数量">1</Cell></Row>
<Row><Cell Name="序号id">30002</Cell><Cell Name="活动ID">300</Cell><Cell Name="活动索引">2</Cell><Cell Name="活动名称">材料兑换</Cell><Cell Name="活动入口">热更福利中心</Cell><Cell Name="兑换次数是否日清">是</Cell><Cell Name="重复兑换次数">1</Cell><Cell Name="兑换收集物品1类型">道具</Cell><Cell Name="兑换收集物品1ID">7002</Cell><Cell Name="兑换收集物品1数量">20</Cell><Cell Name="兑换收集物品2类型">钻石</Cell><Cell Name="兑换收集物品2ID">0</Cell><Cell Name="兑换收集物品2数量">5</Cell><Cell Name="兑换产出物品类型">道具</Cell><Cell Name="兑换产出物品ID">8002</Cell><Cell Name="兑换产出物品数量">2</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "41.svr下发道具信息表_Syndra.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="道具信息"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">7001</Cell><Cell Name="名称">兑换币A</Cell></Row>
<Row><Cell Name="ID">7002</Cell><Cell Name="名称">兑换币B</Cell></Row>
<Row><Cell Name="ID">8001</Cell><Cell Name="名称">奖励箱A</Cell></Row>
<Row><Cell Name="ID">8002</Cell><Cell Name="名称">奖励箱B</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)


def write_collect_exchange_fixture(root: Path) -> None:
	path = root / "Xml" / "Garena" / "TW" / "CommonCore"
	path.mkdir(parents=True)
	(path / "日常活动表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="条件活动表"><Columns><Column Name="活动ID" /></Columns>
<Row><Cell Name="活动ID">901</Cell><Cell Name="活动名称">获取活动币</Cell><Cell Name="条件1简介">完成对局</Cell><Cell Name="条件1目标值">1</Cell><Cell Name="条件1奖励ID">1001</Cell><Cell Name="条件1是否每日刷新">是</Cell></Row>
</Sheet>
<Sheet Name="兑换活动表"><Columns><Column Name="活动ID" /><Column Name="活动索引" /></Columns>
<Row><Cell Name="活动ID">902</Cell><Cell Name="活动索引">1</Cell><Cell Name="活动名称">兑换奖励箱</Cell><Cell Name="兑换次数是否日清">否</Cell><Cell Name="重复兑换次数">3</Cell><Cell Name="兑换收集物品1类型">道具</Cell><Cell Name="兑换收集物品1ID">7001</Cell><Cell Name="兑换收集物品1数量">5</Cell><Cell Name="兑换产出物品类型">道具</Cell><Cell Name="兑换产出物品ID">8001</Cell><Cell Name="兑换产出物品数量">1</Cell></Row>
</Sheet>
<Sheet Name="收集兑换活动表"><Columns><Column Name="活动ID" /></Columns>
<Row><Cell Name="活动ID">900</Cell><Cell Name="活动名称">收集活动币兑换奖励</Cell><Cell Name="活动入口">热更福利中心</Cell><Cell Name="条件活动ID">901</Cell><Cell Name="兑换活动ID">902</Cell></Row>
</Sheet>
</Root>""",
		encoding="utf-8",
	)
	(path / "35.svr下发随机奖励配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="随机奖励配置表"><Columns><Column Name="随机奖励ID" /></Columns>
<Row><Cell Name="随机奖励ID">1001</Cell><Cell Name="随机奖励描述">活动币奖励</Cell><Cell Name="奖励1类型">随机道具</Cell><Cell Name="奖励1ID">7001</Cell><Cell Name="奖励1数量下限">10</Cell><Cell Name="奖励1数量上限">10</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "41.svr下发道具信息表_Syndra.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="道具信息"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">7001</Cell><Cell Name="名称">活动币</Cell></Row>
<Row><Cell Name="ID">8001</Cell><Cell Name="名称">奖励箱</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)


def write_active_point_fixture(root: Path) -> None:
	path = root / "Xml" / "Garena" / "TW" / "CommonCore"
	path.mkdir(parents=True)
	(path / "日常活动表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="条件活动表"><Columns><Column Name="活动ID" /></Columns>
<Row><Cell Name="活动ID">1001</Cell><Cell Name="活动名称">活跃任务</Cell><Cell Name="条件1简介">完成1场对局</Cell><Cell Name="条件1目标值">1</Cell><Cell Name="条件1奖励ID">5001</Cell><Cell Name="条件1是否每日刷新">是</Cell><Cell Name="条件2简介">完成3场对局</Cell><Cell Name="条件2目标值">3</Cell><Cell Name="条件2奖励ID">5002</Cell><Cell Name="条件2是否每日刷新">否</Cell></Row>
</Sheet>
<Sheet Name="活跃度活动表"><Columns><Column Name="活动ID" /></Columns>
<Row><Cell Name="活动ID">1000</Cell><Cell Name="活动名称">活跃度测试活动</Cell><Cell Name="活动入口">热更福利中心</Cell><Cell Name="关联的条件活动ID">1001</Cell><Cell Name="是否邮件发送奖励">是</Cell><Cell Name="最高奖励领取时间">20260831235959</Cell><Cell Name="第1档活跃度要求">10</Cell><Cell Name="第1档奖励">6001</Cell><Cell Name="第2档活跃度要求">20</Cell><Cell Name="第2档奖励">6002</Cell><Cell Name="活跃任务1活跃度数值">5</Cell><Cell Name="活跃任务2活跃度数值">10</Cell></Row>
</Sheet>
</Root>""",
		encoding="utf-8",
	)
	(path / "35.svr下发随机奖励配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="随机奖励配置表"><Columns><Column Name="随机奖励ID" /></Columns>
<Row><Cell Name="随机奖励ID">5001</Cell><Cell Name="随机奖励描述">任务奖励1</Cell><Cell Name="奖励1类型">随机道具</Cell><Cell Name="奖励1ID">7001</Cell><Cell Name="奖励1数量下限">1</Cell><Cell Name="奖励1数量上限">1</Cell></Row>
<Row><Cell Name="随机奖励ID">5002</Cell><Cell Name="随机奖励描述">任务奖励2</Cell><Cell Name="奖励1类型">随机道具</Cell><Cell Name="奖励1ID">7001</Cell><Cell Name="奖励1数量下限">2</Cell><Cell Name="奖励1数量上限">2</Cell></Row>
<Row><Cell Name="随机奖励ID">6001</Cell><Cell Name="随机奖励描述">档位奖励1</Cell><Cell Name="奖励1类型">随机道具</Cell><Cell Name="奖励1ID">8001</Cell><Cell Name="奖励1数量下限">1</Cell><Cell Name="奖励1数量上限">1</Cell></Row>
<Row><Cell Name="随机奖励ID">6002</Cell><Cell Name="随机奖励描述">档位奖励2</Cell><Cell Name="奖励1类型">随机钻石</Cell><Cell Name="奖励1数量下限">20</Cell><Cell Name="奖励1数量上限">20</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "41.svr下发道具信息表_Syndra.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="道具信息"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">7001</Cell><Cell Name="名称">活跃币</Cell></Row>
<Row><Cell Name="ID">8001</Cell><Cell Name="名称">活跃宝箱</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)


def write_sign_in_text_fixture(root: Path) -> None:
	path = root / "Xml" / "Garena" / "TW" / "CommonCore"
	path.mkdir(parents=True)
	(path / "日常活动表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root>
<Sheet Name="条件活动表"><Columns><Column Name="活动ID" /></Columns>
<Row><Cell Name="活动ID">200</Cell><Cell Name="活动名称">预约任务</Cell><Cell Name="条件1简介">完成预约</Cell><Cell Name="条件1目标值">1</Cell><Cell Name="条件1奖励ID">1001</Cell></Row>
</Sheet>
<Sheet Name="签到活动表"><Columns><Column Name="活动ID" /></Columns>
<Row><Cell Name="活动ID">400</Cell><Cell Name="活动名称">七日签到</Cell><Cell Name="活动入口">热更福利中心</Cell><Cell Name="开始时间">20260801000000</Cell><Cell Name="结束时间">20260807235959</Cell><Cell Name="签到类型">累计签到</Cell><Cell Name="中断处理类型">继续</Cell><Cell Name="是否可补签">否</Cell><Cell Name="天数1奖励ID">1001</Cell><Cell Name="天数2奖励ID">1002</Cell><Cell Name="天数2预选ID">88</Cell></Row>
</Sheet>
<Sheet Name="文本活动表"><Columns><Column Name="活动ID" /></Columns>
<Row><Cell Name="活动ID">300</Cell><Cell Name="活动名称">预约送奖励</Cell><Cell Name="活动标题">预约送奖励</Cell><Cell Name="活动简介">完成预约领取奖励</Cell><Cell Name="活动入口">热更福利中心</Cell><Cell Name="按钮文字">立即预约</Cell><Cell Name="按钮跳转入口">Form:120</Cell><Cell Name="关联的活动类型">条件活动</Cell><Cell Name="关联的活动ID">200</Cell></Row>
</Sheet>
</Root>""",
		encoding="utf-8",
	)
	(path / "35.svr下发随机奖励配置表.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="随机奖励配置表"><Columns><Column Name="随机奖励ID" /></Columns>
<Row><Cell Name="随机奖励ID">1001</Cell><Cell Name="奖励1类型">随机道具</Cell><Cell Name="奖励1ID">5001</Cell><Cell Name="奖励1数量下限">10</Cell><Cell Name="奖励1数量上限">10</Cell></Row>
<Row><Cell Name="随机奖励ID">1002</Cell><Cell Name="奖励1类型">随机钻石</Cell><Cell Name="奖励1数量下限">20</Cell><Cell Name="奖励1数量上限">20</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)
	(path / "41.svr下发道具信息表_Syndra.dtxml").write_text(
		"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="道具信息"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">5001</Cell><Cell Name="名称">预约币</Cell></Row>
</Sheet></Root>""",
		encoding="utf-8",
	)


class ChangeSetModuleTests(unittest.TestCase):
	def test_skin_module_loads_current_main_row_and_linked_promotion(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			path = Path(temporary_directory) / "Xml" / "Garena" / "TW" / "CommonCore"
			path.mkdir(parents=True)
			(path / "英雄皮肤促销表.dtxml").write_text(skin_dtxml(), encoding="utf-8")
			changeset = {"changes": [change(
				"英雄皮肤促销表.dtxml",
				"svr下发皮肤促销特卖",
				"促销特卖ID=510152",
				{"促销特卖ID": "510152", "皮肤ID": "51015", "点券价格": "570"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		module = result["modules"][0]
		self.assertEqual("skin", module["module"])
		self.assertEqual("51015", module["items"][0]["object_id"])
		self.assertEqual("15", module["items"][0]["skin_id"])
		self.assertEqual(1, module["item_count"])
		self.assertEqual(2, len(module["items"][0]["promotions"]))
		client_promotion, promotion = module["items"][0]["promotions"]
		self.assertEqual("510151", client_promotion["促销ID"])
		self.assertEqual("皮肤促销特卖", client_promotion["source_sheet"])
		self.assertFalse(client_promotion["changed_in_package"])
		self.assertEqual("510152", promotion["促销ID"])
		self.assertEqual("svr下发皮肤促销特卖", promotion["source_sheet"])
		self.assertTrue(promotion["changed_in_package"])
		self.assertEqual("限定", promotion["促销类型"])
		self.assertEqual("2026-08-11 14:00:00 至 2026-09-02 23:59:59", promotion["促销时间"])
		self.assertEqual("H5获取", promotion["获取方式"])
		self.assertEqual(
			"英雄: 510 莉莉安\n"
			"皮肤: 51015 魔女回憶錄·幻之影\n"
			"促销ID: 510152\n"
			"促销类型: 限定\n"
			"促销时间: 2026-08-11 14:00:00 至 2026-09-02 23:59:59\n"
			"获取方式: H5获取",
			promotion["display_text"],
		)

	def test_skin_module_marks_form_id_acquisition_for_future_mapping(self) -> None:
		from changeset_modules import _acquisition_method

		result = _acquisition_method({"皮肤获取方式跳转入口": '{"FormId":"1203"}'})
		self.assertEqual("待补充", result["method"])
		self.assertEqual("form_id", result["source"])
		self.assertEqual("1203", result["value"])

	def test_activity_module_groups_same_activity_across_sheets(self) -> None:
		changeset = {"changes": [
			change("日常活动表.dtxml", "文本活动表", "活动ID=100", {"活动ID": "100", "活动标题": "活动A"}),
			change("日常活动表.dtxml", "条件活动表", "活动ID=100", {"活动ID": "100", "条件ID": "200"}),
		]}
		result = ModuleRegistry().analyze(changeset, ModuleContext())
		module = result["modules"][0]
		self.assertEqual("activity", module["module"])
		self.assertEqual(1, module["item_count"])
		self.assertEqual(2, len(module["items"][0]["changes"]))
		self.assertIn("活动: 100 活动A", module["items"][0]["display_text"])

	def test_activity_module_loads_all_rows_for_changed_activity(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			path = Path(temporary_directory) / "Xml" / "Garena" / "TW" / "CommonCore"
			path.mkdir(parents=True)
			(path / "日常活动表.dtxml").write_text(
				"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="兑换活动表"><Columns><Column Name="活动ID" /><Column Name="活动索引" /></Columns>
<Row><Cell Name="活动ID">100</Cell><Cell Name="活动索引">1</Cell></Row>
<Row><Cell Name="活动ID">100</Cell><Cell Name="活动索引">2</Cell></Row>
</Sheet></Root>""",
				encoding="utf-8",
			)
			changeset = {"changes": [change(
				"日常活动表.dtxml",
				"兑换活动表",
				"活动ID=100, 活动索引=1",
				{"活动ID": "100", "活动索引": "1"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)
		self.assertEqual(2, len(result["modules"][0]["items"][0]["current_state"]))

	def test_exchange_activity_builds_all_exchange_items(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_exchange_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"日常活动表.dtxml",
				"兑换活动表",
				"活动ID=300, 活动索引=1",
				{
					"活动ID": "300",
					"活动索引": "1",
					"兑换收集物品1数量": "10",
				},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = result["modules"][0]["items"][0]
		content = item["activity_content"]
		self.assertEqual("exchange_activity", content["kind"])
		self.assertEqual(2, len(content["data"]["exchanges"]))
		first, second = content["data"]["exchanges"]
		self.assertEqual("兑换币A", first["costs"][0]["name"])
		self.assertEqual("奖励箱A", first["output"]["name"])
		self.assertEqual("否", first["reset_daily"])
		self.assertEqual("5", first["repeat_limit"])
		self.assertIn("兑换收集物品1数量", first["change_context"]["direct_fields"])
		self.assertEqual("钻石", second["costs"][1]["type"])
		self.assertIsNone(second["costs"][1]["resolved"])
		self.assertEqual([], content["data"]["unresolved_references"])
		self.assertIn("兑换项数量: 2", item["display_text"])

	def test_item_change_finds_complete_existing_exchange_activity(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_exchange_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"41.svr下发道具信息表_Syndra.dtxml",
				"道具信息",
				"ID=7001",
				{"ID": "7001", "名称": "兑换币A"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		activity_module = next(module for module in result["modules"] if module["module"] == "activity")
		item = activity_module["items"][0]
		self.assertEqual("300", item["object_id"])
		self.assertEqual("兑换活动表", item["activity_type"])
		self.assertEqual(2, len(item["activity_content"]["data"]["exchanges"]))
		first, second = item["activity_content"]["data"]["exchanges"]
		self.assertEqual(1, len(first["change_context"]["indirect_impacts"]))
		self.assertEqual([], second["change_context"]["indirect_impacts"])
		self.assertIn("道具 7001 → 兑换收集物品1ID", item["display_text"])

	def test_collect_exchange_activity_combines_acquisition_and_exchange(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_collect_exchange_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"日常活动表.dtxml",
				"收集兑换活动表",
				"活动ID=900",
				{"活动ID": "900", "条件活动ID": "901", "兑换活动ID": "902"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = result["modules"][0]["items"][0]
		content = item["activity_content"]
		self.assertEqual("collect_exchange_activity", content["kind"])
		data = content["data"]
		self.assertEqual("901", data["condition_activity_id"])
		self.assertEqual("902", data["exchange_activity_id"])
		self.assertEqual(1, len(data["condition_activity"]["conditions"]))
		self.assertEqual(1, len(data["exchange_activity"]["exchanges"]))
		self.assertEqual("7001", data["material_flow"]["links"][0]["item_id"])
		self.assertEqual("活动币", data["material_flow"]["links"][0]["item_name"])
		self.assertEqual([], data["unresolved_references"])
		self.assertIn("材料关联: 7001 活动币", item["display_text"])

	def test_reward_change_propagates_through_condition_to_collect_exchange(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_collect_exchange_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"35.svr下发随机奖励配置表.dtxml",
				"随机奖励配置表",
				"随机奖励ID=1001",
				{"随机奖励ID": "1001", "奖励1ID": "7001"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		activity_module = next(module for module in result["modules"] if module["module"] == "activity")
		parent = next(item for item in activity_module["items"] if item["object_id"] == "900")
		self.assertEqual("collect_exchange_activity", parent["activity_content"]["kind"])
		impact = parent["impact_reasons"][0]
		self.assertEqual("901", impact["via_activity_id"])
		self.assertEqual("条件活动表", impact["child_sheet"])
		self.assertEqual("1001", impact["via_reward_id"])
		self.assertIn("奖励 1001 → 条件活动表 901 → 条件活动ID", parent["display_text"])

	def test_exchange_child_change_marks_collect_exchange_parent(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_collect_exchange_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"日常活动表.dtxml",
				"兑换活动表",
				"活动ID=902, 活动索引=1",
				{"活动ID": "902", "活动索引": "1", "兑换产出物品数量": "1"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		activity_module = next(module for module in result["modules"] if module["module"] == "activity")
		parent = next(item for item in activity_module["items"] if item["object_id"] == "900")
		self.assertEqual([], parent["changes"])
		self.assertEqual("902", parent["impact_reasons"][0]["via_activity_id"])
		self.assertIn("子活动 902 → 兑换活动表 902 → 兑换活动ID", parent["display_text"])

	def test_active_point_activity_combines_tasks_points_and_tiers(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_active_point_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"日常活动表.dtxml",
				"活跃度活动表",
				"活动ID=1000",
				{
					"活动ID": "1000",
					"活跃任务1活跃度数值": "5",
					"第1档奖励": "6001",
				},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = result["modules"][0]["items"][0]
		content = item["activity_content"]
		self.assertEqual("active_point_activity", content["kind"])
		data = content["data"]
		self.assertEqual("1001", data["condition_activity_id"])
		tasks = data["condition_activity"]["conditions"]
		self.assertEqual("5", tasks[0]["activity_points"])
		self.assertEqual("10", tasks[1]["activity_points"])
		self.assertEqual("是", tasks[0]["refresh_daily"])
		self.assertEqual(["活跃任务1活跃度数值"], tasks[0]["change_context"]["direct_fields"])
		self.assertEqual(2, len(data["tiers"]))
		self.assertEqual("10", data["tiers"][0]["requirement"])
		self.assertEqual("活跃宝箱", data["tiers"][0]["reward"]["components"][0]["item_name"])
		self.assertEqual(["第1档奖励"], data["tiers"][0]["change_context"]["direct_fields"])
		self.assertEqual("2026-08-31 23:59:59", data["highest_reward_claim_time"])
		self.assertEqual([], data["unresolved_references"])
		self.assertIn("活跃任务1: 完成1场对局 | 活跃度 5", item["display_text"])
		self.assertIn("第1档: 10 活跃度 → 奖励 道具 8001 活跃宝箱 ×1", item["display_text"])
		self.assertIn("第2档: 20 活跃度 → 奖励 钻石 ×20", item["display_text"])

	def test_nested_reward_resolves_to_final_item_content(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			path = Path(temporary_directory) / "Xml" / "Garena" / "TW" / "CommonCore"
			path.mkdir(parents=True)
			(path / "35.svr下发随机奖励配置表.dtxml").write_text(
				"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="随机奖励配置表"><Columns><Column Name="随机奖励ID" /></Columns>
<Row><Cell Name="随机奖励ID">9001</Cell><Cell Name="随机奖励描述">外层宝箱</Cell><Cell Name="奖励1类型">随机嵌套</Cell><Cell Name="奖励1ID">9002</Cell><Cell Name="奖励1数量下限">2</Cell><Cell Name="奖励1数量上限">2</Cell></Row>
<Row><Cell Name="随机奖励ID">9002</Cell><Cell Name="随机奖励描述">内层宝箱</Cell><Cell Name="奖励1类型">随机道具</Cell><Cell Name="奖励1ID">5001</Cell><Cell Name="奖励1数量下限">3</Cell><Cell Name="奖励1数量上限">3</Cell></Row>
</Sheet></Root>""",
				encoding="utf-8",
			)
			(path / "41.svr下发道具信息表_Syndra.dtxml").write_text(
				"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="道具信息"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">5001</Cell><Cell Name="名称">活动兑换币</Cell></Row>
</Sheet></Root>""",
				encoding="utf-8",
			)
			changeset = {"changes": [change(
				"35.svr下发随机奖励配置表.dtxml",
				"随机奖励配置表",
				"随机奖励ID=9001",
				{"随机奖励ID": "9001", "奖励1类型": "随机嵌套", "奖励1ID": "9002"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		reward_module = next(module for module in result["modules"] if module["module"] == "reward")
		item = reward_module["items"][0]
		leaf = item["current_state"]["leaf_rewards"][0]
		self.assertEqual("道具", leaf["entity_type"])
		self.assertEqual("5001", leaf["entity_id"])
		self.assertEqual("活动兑换币", leaf["entity_name"])
		self.assertEqual("6", leaf["quantity_min"])
		self.assertEqual(["9001", "9002"], leaf["reward_path"])
		self.assertIn("最终内容: 道具 5001 活动兑换币 ×6", item["display_text"])

	def test_active_tier_reward_change_finds_existing_active_activity(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_active_point_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"35.svr下发随机奖励配置表.dtxml",
				"随机奖励配置表",
				"随机奖励ID=6001",
				{"随机奖励ID": "6001", "奖励1ID": "8001"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		activity_module = next(module for module in result["modules"] if module["module"] == "activity")
		item = next(item for item in activity_module["items"] if item["object_id"] == "1000")
		self.assertEqual("active_point_activity", item["activity_content"]["kind"])
		self.assertEqual("1", item["impact_reasons"][0]["tier_index"])
		self.assertEqual(1, len(item["activity_content"]["data"]["tiers"][0]["change_context"]["indirect_impacts"]))
		self.assertIn("奖励 6001 → 第1档奖励", item["display_text"])

	def test_condition_reward_change_propagates_to_active_activity_task(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_active_point_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"35.svr下发随机奖励配置表.dtxml",
				"随机奖励配置表",
				"随机奖励ID=5001",
				{"随机奖励ID": "5001", "奖励1ID": "7001"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		activity_module = next(module for module in result["modules"] if module["module"] == "activity")
		item = next(item for item in activity_module["items"] if item["object_id"] == "1000")
		impact = item["impact_reasons"][0]
		self.assertEqual("1001", impact["via_activity_id"])
		self.assertEqual("1", impact["condition_index"])
		task = item["activity_content"]["data"]["condition_activity"]["conditions"][0]
		self.assertEqual(1, len(task["change_context"]["indirect_impacts"]))
		self.assertIn("奖励 5001 → 条件活动表 1001 → 关联的条件活动ID", item["display_text"])

	def test_welfare_activity_integrates_referenced_daily_activity(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			path = Path(temporary_directory) / "Xml" / "Garena" / "TW" / "CommonCore"
			path.mkdir(parents=True)
			(path / "日常活动表.dtxml").write_text(
				"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="条件活动表"><Columns><Column Name="活动ID" /></Columns>
<Row><Cell Name="活动ID">200001441</Cell><Cell Name="活动名称">每日分享送奖励</Cell><Cell Name="条件1奖励ID">1001</Cell></Row>
</Sheet></Root>""",
				encoding="utf-8",
			)
			changeset = {"changes": [change(
				"157.ilua热更活动聚合配置表.dtxml",
				"ilua聚合配置表",
				"活动ID=529",
				{
					"活动ID": "529",
					"活动名称": "每日分享送奖励",
					"活动入口": "福利",
					"活动详情的json串": '{"ActivityID":200001441}',
				},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)
		item = result["modules"][0]["items"][0]
		self.assertEqual(["200001441"], item["reference_ids"])
		self.assertEqual("条件活动表", item["related_activities"][0]["sheet"])
		self.assertIn("关联活动: 200001441 每日分享送奖励 (条件活动表)", item["display_text"])

	def test_reward_change_finds_existing_condition_activity_from_current_snapshot(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_activity_impact_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"35.svr下发随机奖励配置表.dtxml",
				"随机奖励配置表",
				"随机奖励ID=1001",
				{"随机奖励ID": "1001", "奖励1ID": "5001", "奖励1数量下限": "10"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		activity_module = next(module for module in result["modules"] if module["module"] == "activity")
		item = activity_module["items"][0]
		self.assertEqual("200001441", item["object_id"])
		self.assertEqual("条件活动表", item["activity_type"])
		self.assertEqual([], item["changes"])
		self.assertEqual("1001", item["impact_reasons"][0]["via_reward_id"])
		self.assertEqual("条件1奖励ID", item["impact_reasons"][0]["field"])
		self.assertEqual("分享币", item["affected_rewards"][0]["components"][0]["item_name"])
		self.assertIn("奖励 1001 → 条件1奖励ID", item["display_text"])
		condition = item["activity_content"]["data"]["conditions"][0]
		self.assertEqual("每日分享1次", condition["description"])
		self.assertEqual("1", condition["target_value"])
		self.assertEqual([{"position": 1, "value": "21"}], condition["parameters"])
		self.assertEqual("否", condition["refresh_daily"])
		self.assertEqual("1001", condition["reward"]["reward_id"])
		self.assertEqual(1, len(condition["change_context"]["indirect_impacts"]))

	def test_output_limit_module_maps_limited_slot_to_reward_and_gift_caller(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"48.礼包产出控制表.dtxml",
				"礼包产出控制",
				"随机奖励ID=2002",
				{
					"随机奖励ID": "2002",
					"指定物品1每日上限": "10",
					"指定物品1总上限": "100",
					"指定物品1控制间隔": "3600",
					"指定物品1控制间隔产出上限": "3",
				},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		module = next(module for module in result["modules"] if module["module"] == "output_limit")
		item = module["items"][0]
		slot = item["limit_slots"][0]
		self.assertEqual("2002", item["object_id"])
		self.assertEqual(1, item["limited_slot_count"])
		self.assertEqual(1, slot["slot_index"])
		self.assertEqual("10", slot["daily_limit"])
		self.assertEqual("100", slot["total_limit"])
		self.assertEqual("3600", slot["control_interval"])
		self.assertEqual("3", slot["interval_output_limit"])
		self.assertEqual("9010", slot["leaf_rewards"][0]["entity_id"])
		self.assertEqual("都市传说币", slot["leaf_rewards"][0]["entity_name"])
		self.assertEqual("9023", item["callers"]["gift_items"][0]["item_id"])
		self.assertIn("奖励1: 道具 9010 都市传说币 ×300", item["display_text"])
		self.assertIn("每日上限=10 | 总上限=100 | 控制间隔=3600 | 间隔产出上限=3", item["display_text"])
		self.assertEqual(1, result["overview"]["limited_reward_count"])
		self.assertEqual(1, result["overview"]["limited_slot_count"])
		self.assertEqual("限量奖励组", result["overview"]["content_updates"][0]["label"])
		self.assertIn("限量产出: 1组随机奖励，1个受限奖励槽位", result["overview"]["display_text"])

	def test_condition_activity_builds_fact_tree_without_running_rules(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_activity_impact_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"日常活动表.dtxml",
				"条件活动表",
				"活动ID=200001441",
				{
					"活动ID": "200001441",
					"条件1目标值": "1",
					"条件1奖励ID": "1001",
				},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = result["modules"][0]["items"][0]
		content = item["activity_content"]
		self.assertEqual("condition_activity", content["kind"])
		self.assertEqual("热更福利中心", item["current_state"][0]["fields"]["活动入口"])
		self.assertEqual("是", content["data"]["refresh_daily"])
		self.assertEqual("活动团队_单人", content["data"]["team_type"])
		condition = content["data"]["conditions"][0]
		self.assertEqual(["条件1奖励ID", "条件1目标值"], condition["change_context"]["direct_fields"])
		self.assertEqual("否", condition["refresh_daily"])
		self.assertIn("每日刷新 否", item["display_text"])
		self.assertEqual([], content["data"]["unresolved_references"])
		self.assertNotIn("校验结果", item["display_text"])

	def test_item_change_finds_existing_activity_through_reward(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_activity_impact_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"41.svr下发道具信息表_Syndra.dtxml",
				"道具信息",
				"ID=5001",
				{"ID": "5001", "名称": "分享币"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		activity_module = next(module for module in result["modules"] if module["module"] == "activity")
		item = activity_module["items"][0]
		self.assertEqual("200001441", item["object_id"])
		self.assertEqual("item", item["impact_reasons"][0]["trigger_type"])
		self.assertEqual("5001", item["impact_reasons"][0]["trigger_id"])
		self.assertEqual("1001", item["impact_reasons"][0]["via_reward_id"])
		self.assertIn("道具 5001 → 奖励 1001 → 条件1奖励ID", item["display_text"])

	def test_sign_in_activity_resolves_each_day_reward_and_overview(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_sign_in_text_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"日常活动表.dtxml",
				"签到活动表",
				"活动ID=400",
				{"活动ID": "400", "天数1奖励ID": "1001", "天数2奖励ID": "1002"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = result["modules"][0]["items"][0]
		content = item["activity_content"]
		self.assertEqual("sign_in_activity", content["kind"])
		self.assertEqual("预约币", content["data"]["days"][0]["reward"]["leaf_rewards"][0]["entity_name"])
		self.assertEqual("88", content["data"]["days"][1]["preselection_id"])
		self.assertIn("第2天: 钻石 ×20", item["display_text"])
		self.assertEqual("签到活动", result["overview"]["activity_updates"][0]["label"])
		self.assertEqual(1, result["overview"]["activity_updates"][0]["count"])
		self.assertEqual("interpreted", result["overview"]["activity_updates"][0]["detail_status"])
		self.assertFalse(result["overview"]["has_structural_risk"])
		self.assertEqual("not_enabled", result["overview"]["business_rule_status"])

	def test_text_activity_includes_buttons_and_linked_condition_content(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_sign_in_text_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"日常活动表.dtxml",
				"文本活动表",
				"活动ID=300",
				{"活动ID": "300", "按钮文字": "立即预约", "关联的活动ID": "200"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = result["modules"][0]["items"][0]
		data = item["activity_content"]["data"]
		self.assertEqual("text_activity", item["activity_content"]["kind"])
		self.assertEqual("Form:120", data["buttons"][0]["entry"])
		self.assertTrue(data["linked_resolved"])
		self.assertEqual("condition_activity", data["linked_activity"]["kind"])
		self.assertIn("关联条件1: 完成预约 | 目标 1 | 奖励 道具 5001 预约币 ×10", item["display_text"])

	def test_reward_entity_change_propagates_to_sign_in_activity(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_sign_in_text_fixture(Path(temporary_directory))
			path = Path(temporary_directory) / "Xml" / "Garena" / "TW" / "CommonCore"
			reward_path = path / "35.svr下发随机奖励配置表.dtxml"
			reward_path.write_text(
				reward_path.read_text(encoding="utf-8").replace(
					'<Cell Name="奖励1类型">随机钻石</Cell><Cell Name="奖励1数量下限">20</Cell><Cell Name="奖励1数量上限">20</Cell>',
					'<Cell Name="奖励1类型">随机皮肤</Cell><Cell Name="奖励1ID">51015</Cell><Cell Name="奖励1数量下限">1</Cell><Cell Name="奖励1数量上限">1</Cell>',
				),
				encoding="utf-8",
			)
			(path / "73.svr下发皮肤配置表.dtxml").write_text(
				"""<?xml version="1.0" encoding="utf-8"?>
<Root><Sheet Name="皮肤配置表"><Columns><Column Name="ID" /></Columns>
<Row><Cell Name="ID">51015</Cell><Cell Name="皮肤名称">魔女回憶錄·幻之影</Cell></Row>
</Sheet></Root>""",
				encoding="utf-8",
			)
			changeset = {"changes": [change(
				"73.svr下发皮肤配置表.dtxml",
				"皮肤配置表",
				"ID=51015",
				{"ID": "51015", "皮肤名称": "魔女回憶錄·幻之影"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		activity_module = next(module for module in result["modules"] if module["module"] == "activity")
		item = next(item for item in activity_module["items"] if item["object_id"] == "400")
		impact = item["impact_reasons"][0]
		self.assertEqual("entity", impact["trigger_type"])
		self.assertEqual("皮肤", impact["trigger_entity_type"])
		self.assertEqual("1002", impact["via_reward_id"])
		self.assertEqual("2", impact["day_index"])
		self.assertIn("皮肤 51015 → 奖励 1002 → 天数2奖励ID", item["display_text"])
		self.assertEqual(1, result["overview"]["related_activity_count"])

	def test_item_reward_change_propagates_into_text_wrapper(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_sign_in_text_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"41.svr下发道具信息表_Syndra.dtxml",
				"道具信息",
				"ID=5001",
				{"ID": "5001", "名称": "预约币"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		activity_module = next(module for module in result["modules"] if module["module"] == "activity")
		activity_ids = {item["object_id"] for item in activity_module["items"]}
		self.assertEqual({"200", "300", "400"}, activity_ids)
		text_item = next(item for item in activity_module["items"] if item["object_id"] == "300")
		self.assertEqual("text_activity", text_item["activity_content"]["kind"])
		self.assertIn("条件活动表 200 → 关联的活动ID", text_item["display_text"])
		self.assertEqual(3, result["overview"]["related_activity_count"])

	def test_item_module_interprets_category_references_and_validity(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_business_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"41.svr下发道具信息表_Syndra.dtxml",
				"道具信息",
				"ID=5001",
				{"ID": "5001", "名称": "夏日纪念币", "类型": "普通道具"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item_module = next(module for module in result["modules"] if module["module"] == "item")
		item = item_module["items"][0]
		self.assertEqual("普通道具", item["category"])
		self.assertEqual("activity_token", item["category_usage"]["kind"])
		self.assertTrue(item["category_usage"]["resolved"])
		self.assertEqual("hybrid", item["category_usage"]["content"]["business_mode"])
		self.assertEqual(1, item["category_usage"]["content"]["acquisition_activity_count"])
		self.assertEqual(
			["条件1奖励ID", "条件2奖励ID"],
			item["category_usage"]["content"]["acquisition_activities"][0]["fields"],
		)
		self.assertEqual(1, item["category_usage"]["content"]["consumption_activity_count"])
		self.assertEqual(1, item["category_usage"]["content"]["related_activity_count"])
		self.assertEqual("603", item["category_usage"]["content"]["progress_activities"][0]["activity_id"])
		self.assertEqual(
			["3", "7"],
			[stage["target_value"] for stage in item["category_usage"]["content"]["progress_activities"][0]["stages"]],
		)
		self.assertEqual("700", item["category_usage"]["content"]["ilua_activities"][0]["activity_id"])
		self.assertIn("作为活动奖励发放", item["purpose"])
		self.assertEqual(
			{"随机奖励配置表", "条件活动表", "兑换活动表", "收集兑换活动表", "通用条件配置表", "ilua聚合配置表"},
			{reference["sheet"] for reference in item["references"]},
		)
		self.assertEqual("passed", item["validity"]["checks"][0]["status"])
		self.assertEqual(168, item["validity"]["checks"][0]["activity_duration_hours"])
		self.assertIn("活动 Token: 5001 夏日纪念币", item["display_text"])
		self.assertIn("业务模式: 累计进度 + 兑换混合型", item["display_text"])
		self.assertIn("获取活动: 条件活动 600 收集纪念币", item["display_text"])
		self.assertIn("进度活动: 条件活动 603 纪念币累计进度", item["display_text"])
		self.assertIn("进度档位: 3 → 钻石 ×20; 7 → 钻石 ×20", item["display_text"])
		self.assertIn("兑换消耗: 兑换活动 601 纪念币兑换奖励（索引 1）", item["display_text"])
		self.assertIn("归属活动: 收集兑换活动 602 夏日纪念币收集活动", item["display_text"])
		self.assertNotIn("品质:", item["display_text"])

	def test_item_module_warns_when_limited_hours_are_shorter_than_activity(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_business_fixture(Path(temporary_directory), limited_hours="24")
			changeset = {"changes": [change(
				"41.svr下发道具信息表_Syndra.dtxml",
				"道具信息",
				"ID=5001",
				{"ID": "5001", "名称": "夏日纪念币", "类型": "普通道具"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		check = item["validity"]["checks"][0]
		self.assertEqual("warning", check["status"])
		self.assertIn("24 小时短于活动持续 168 小时", check["message"])

	def test_item_module_reserves_deferred_categories_without_parsing(self) -> None:
		for item_id, item_name, category in (
			("61011", "装备进阶石", "装备进阶材料"),
			("130001", "月卡", "月卡和周卡"),
			("10035", "[ex]金币赛门票", "门票类(不可主动使用、不可出售)"),
			("11009551", "傳說Prime(30天)", "扫荡券"),
		):
			with self.subTest(category=category):
				changeset = {"changes": [change(
					"41.svr下发道具信息表_Syndra.dtxml",
					"道具信息",
					f"ID={item_id}",
					{"ID": item_id, "名称": item_name, "类型": category},
				)]}
				result = ModuleRegistry().analyze(changeset, ModuleContext())

				item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
				self.assertEqual("deferred_category", item["category_usage"]["kind"])
				self.assertEqual("reserved", item["category_usage"]["content"]["status"])
				self.assertIn("已预留，当前版本暂不展开", item["display_text"])

	def test_item_module_resolves_category_specific_content_tables(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_business_fixture(Path(temporary_directory))
			changeset = {"changes": [
				change(
					"41.svr下发道具信息表_Syndra.dtxml",
					"道具信息",
					"ID=5002",
					{"ID": "5002", "名称": "钻石礼包", "类型": "礼包道具"},
				),
				change(
					"41.svr下发道具信息表_Syndra.dtxml",
					"道具信息",
					"ID=5003",
					{"ID": "5003", "名称": "自选礼包", "类型": "延后领用礼包"},
				),
			]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		items = {
			item["object_id"]: item
			for item in next(module for module in result["modules"] if module["module"] == "item")["items"]
		}
		gift = items["5002"]["category_usage"]
		self.assertEqual("random_reward_gift", gift["kind"])
		self.assertTrue(gift["resolved"])
		self.assertEqual("钻石", gift["content"]["leaf_rewards"][0]["entity_type"])
		self.assertEqual("outbound", next(
			reference for reference in items["5002"]["references"] if reference["role"] == "gift_content"
		)["direction"])

		delay_gift = items["5003"]["category_usage"]
		self.assertEqual("delay_draw_gift", delay_gift["kind"])
		self.assertTrue(delay_gift["resolved"])
		self.assertEqual(2, len(delay_gift["content"]["choices"]))
		self.assertEqual("1", delay_gift["content"]["select_count"])

	def test_item_module_merges_client_changes_and_prefers_server_definition(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [
				change(
					"【运营配置】41.道具信息表_Syndra.dtxml",
					"道具信息",
					"ID=9001",
					{"ID": "9001", "名称": "客户端主表道具", "类型": "普通道具"},
				),
				change(
					"【运营配置】41.道具信息表_Syndra.dtxml",
					"道具信息增量",
					"ID=9001",
					{"ID": "9001", "名称": "客户端增量道具", "类型": "礼包道具"},
				),
			]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item_module = next(module for module in result["modules"] if module["module"] == "item")
		item = item_module["items"][0]
		self.assertEqual(2, item_module["matched_change_count"])
		self.assertEqual(1, item_module["item_count"])
		self.assertEqual(2, len(item["changes"]))
		self.assertEqual("服务器生效道具", item["name"])
		self.assertEqual("头像框资源", item["category"])
		self.assertEqual("server", item["source_resolution"]["selected_source_kind"])
		self.assertTrue(item["source_resolution"]["category_conflict"])
		self.assertEqual({"普通道具", "礼包道具", "头像框资源"}, set(item["source_resolution"]["categories"]))
		self.assertEqual("item_category_conflict", item_module["warnings"][0]["type"])
		self.assertIn("按优先级采用 头像框资源", item["display_text"])

	def test_item_module_uses_client_increment_when_server_definition_is_missing(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9002",
				{"ID": "9002", "名称": "仅增量道具", "类型": "快捷消息"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		self.assertEqual("仅增量道具", item["name"])
		self.assertEqual("快捷消息", item["category"])
		self.assertEqual("client_increment", item["source_resolution"]["selected_source_kind"])
		self.assertFalse(item["source_resolution"]["category_conflict"])
		self.assertEqual("quick_message", item["category_usage"]["kind"])
		self.assertTrue(item["category_usage"]["resolved"])
		self.assertEqual("耶 怎么样啊?", item["category_usage"]["content"]["text"])
		self.assertEqual("胆大党", item["category_usage"]["content"]["theme_name"])
		self.assertEqual("2026-08-01 00:00:00", item["category_usage"]["content"]["theme_start_time"])
		self.assertIn("快捷消息: 412 耶 怎么样啊?", item["display_text"])
		self.assertIn("消息主题: 38 胆大党", item["display_text"])

	def test_item_module_resolves_avatar_and_frame_resources_with_server_priority(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [
				change(
					"【运营配置】41.道具信息表_Syndra.dtxml",
					"道具信息增量",
					"ID=9003",
					{"ID": "9003", "类型": "头像道具"},
				),
				change(
					"【运营配置】41.道具信息表_Syndra.dtxml",
					"道具信息增量",
					"ID=9004",
					{"ID": "9004", "类型": "头像框资源"},
				),
			]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		items = {
			item["object_id"]: item
			for item in next(module for module in result["modules"] if module["module"] == "item")["items"]
		}
		avatar = items["9003"]["category_usage"]
		self.assertEqual("resource_unlock", avatar["kind"])
		self.assertEqual("高速婆婆头像", avatar["content"]["resource_name"])
		self.assertEqual("server", avatar["content"]["source_kind"])
		self.assertEqual(2, len(avatar["content"]["available_sources"]))

		frame = items["9004"]["category_usage"]
		self.assertEqual("高速婆婆相框", frame["content"]["resource_name"])
		self.assertEqual("server_increment", frame["content"]["source_kind"])
		self.assertEqual("2026-08-01 00:00:00", frame["content"]["display_start_time"])
		self.assertIn("解锁资源: 头像框 1008 高速婆婆相框", items["9004"]["display_text"])

	def test_item_module_resolves_battle_effect_definition_listing_and_duration(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9005",
				{"ID": "9005", "类型": "单局特效"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("battle_effect", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("41612", usage["content"]["effect_id"])
		self.assertEqual("給你0分", usage["content"]["effect_name"])
		self.assertEqual("单局表情", usage["content"]["effect_type"])
		self.assertEqual("Prefab/Emoji_41612", usage["content"]["resource_file"])
		self.assertEqual("1 天", usage["content"]["duration_label"])
		self.assertEqual("2026-07-25 10:00:00", usage["content"]["listed_at"])
		self.assertEqual("server", usage["content"]["listing_source_kind"])
		self.assertIn("单局特效: 41612 給你0分", item["display_text"])
		self.assertIn("特效类型: 单局表情 | 有效时长: 1 天", item["display_text"])

	def test_item_module_resolves_gendered_dimensional_parts(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9006",
				{"ID": "9006", "类型": "次元部件道具"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("dimensional_parts", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("区分男女性别", usage["content"]["gender_mode"])
		self.assertEqual(2, len(usage["content"]["parts"]))
		male, female = usage["content"]["parts"]
		self.assertEqual(("61007009", "男", "头套", "高速婆婆男款"), (
			male["part_id"], male["gender"], male["part_type"], male["name"],
		))
		self.assertEqual("server", male["listing_source_kind"])
		self.assertEqual(("62007009", "女"), (female["part_id"], female["gender"]))
		self.assertEqual(2, len([
			reference for reference in item["references"]
			if reference["role"] == "item_resource_content"
		]))
		self.assertIn("次元部件(男): 61007009 高速婆婆男款 | 头套 | 投放ID=30119", item["display_text"])

	def test_item_module_resolves_gendered_dimensional_theme_components(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9007",
				{"ID": "9007", "类型": "次元主题道具"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("dimensional_themes", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual(2, len(usage["content"]["themes"]))
		male, female = usage["content"]["themes"]
		self.assertEqual(("7007", "男", "服务器男主题", "40014"), (
			male["theme_id"], male["gender"], male["name"], male["release_id"],
		))
		self.assertEqual(["31007003", "41007003"], [part["part_id"] for part in male["components"]])
		self.assertTrue(all(part["resolved"] for part in male["components"]))
		self.assertEqual(("7008", "女"), (female["theme_id"], female["gender"]))
		self.assertEqual("server", male["listing_source_kind"])
		self.assertIn("次元主题(男): 7007 服务器男主题 | 投放ID=40014", item["display_text"])
		self.assertIn("主题部件: 31007003 男款高校上衣, 41007003 男款高校下装", item["display_text"])

	def test_item_module_resolves_valorpass_points_and_season(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"41.svr下发道具信息表_Syndra.dtxml",
				"道具信息",
				"ID=9008",
				{"ID": "9008", "类型": "VALORPASS积分卡"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("valorpass_points", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("92", usage["content"]["season"]["season_id"])
		self.assertEqual("2026-08-01 00:00:00", usage["content"]["season"]["start_time"])
		self.assertEqual("50", usage["content"]["point_rewards"][0]["quantity"])
		self.assertIn("增加积分: 50 | 奖励ID=2001", item["display_text"])

	def test_item_module_resolves_valorpass_unlock_tier_with_server_priority(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"41.svr下发道具信息表_Syndra.dtxml",
				"道具信息",
				"ID=9009",
				{"ID": "9009", "类型": "VP通行证"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("valorpass_unlock", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("精英通行证（精英圣典）", usage["content"]["pass_type"])
		self.assertEqual("svr下发解锁表", usage["content"]["unlock_source_sheet"])
		self.assertEqual("699", usage["content"]["discount_price"])
		self.assertEqual("9009", usage["content"]["configured_elite_item_id"])
		self.assertIn("价格配置: 点券 原价=3650 折后价=699", item["display_text"])

	def test_item_module_interprets_mini_app_cloud_points_as_self_contained_currency(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"41.svr下发道具信息表_Syndra.dtxml",
				"道具信息",
				"ID=9010",
				{"ID": "9010", "类型": "小应用云积分"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("mini_app_cloud_points", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("324601", usage["content"]["points_id"])
		self.assertIn("小应用云积分: 货币ID=324601 | 每个道具增加 1", item["display_text"])

	def test_item_module_resolves_limited_voucher_amount_and_batch_schedule(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9011",
				{"ID": "9011", "类型": "限定点券"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("limited_vouchers", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("500", usage["content"]["amount"])
		self.assertEqual("runtime_by_date", usage["content"]["batch_binding"])
		self.assertEqual("8", usage["content"]["latest_configured_batch"]["batch_id"])
		self.assertIn("限定点券: 500", item["display_text"])
		self.assertIn("道具未固定批次", item["display_text"])
		self.assertIn("最新配置批次: 8 | 2026-08-17 00:00:00 至 2026-12-31 23:59:59", item["display_text"])

	def test_item_module_resolves_activity_draw_batch_pools_and_final_rewards(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"41.svr下发道具信息表_Syndra.dtxml",
				"道具信息",
				"ID=9012",
				{"ID": "9012", "类型": "活动抽奖礼包"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("activity_draw_gift", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("10", usage["content"]["batch_id"])
		self.assertEqual(3, usage["content"]["pool_count"])
		self.assertEqual(4, usage["content"]["reward_group_count"])
		self.assertEqual(4, usage["content"]["final_reward_count"])
		main_pool, guarantee_pool, interval_pool = usage["content"]["pools"]
		self.assertEqual(("main", "1100", 2), (
			main_pool["role"], main_pool["pool_id"], main_pool["reward_group_count"],
		))
		self.assertEqual(("15", "1"), (
			guarantee_pool["required_draws"], guarantee_pool["repeatable"],
		))
		self.assertEqual(("1200", "奖励池"), (interval_pool["pool_id"], interval_pool["source_sheet"]))
		self.assertEqual("50圣典积分奖励", main_pool["rewards"][0]["reward"]["description"])
		self.assertIn("奖池概况: 3 个奖池，4 组奖励，展开后 4 项最终内容", item["display_text"])
		self.assertIn("保底节点: 15抽->1101(循环)", item["display_text"])

	def test_item_module_resolves_intimacy_gift_points_and_display_effect(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"41.svr下发道具信息表_Syndra.dtxml",
				"道具信息",
				"ID=9013",
				{"ID": "9013", "类型": "亲密度礼物"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("intimacy_gift", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("15", usage["content"]["intimacy_points"])
		self.assertEqual("双方", usage["content"]["recipient_scope"])
		self.assertEqual("UI_FriendRelationGiveGift_DrtRose", usage["content"]["effect_resource"])
		self.assertEqual("HiFive！我们传说对决", usage["content"]["display_description"])
		self.assertIn("亲密度礼物: 特殊亲密度道具 | 双方 +15 点", item["display_text"])
		self.assertIn("显示时长: 10-30 秒", item["display_text"])

	def test_item_module_resolves_specified_skin_discount_coupon(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9014",
				{"ID": "9014", "类型": "折扣券"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("purchase_coupon", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("percentage", usage["content"]["discount_mode"])
		self.assertEqual("指定皮肤", usage["content"]["target_type"])
		self.assertEqual("克里希·樱吹雪", usage["content"]["targets"][0]["entity_name"])
		self.assertEqual("2026-04-10 23:59:59", usage["content"]["usable_end_time"])
		self.assertIn("优惠券: 折扣券 | 支付原价 80%（8折）", item["display_text"])
		self.assertIn("指定对象组: 1085 | 10618 克里希·樱吹雪", item["display_text"])

	def test_item_module_interprets_threshold_fixed_amount_coupon(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9015",
				{"ID": "9015", "类型": "满减抵价券"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("fixed_amount", usage["content"]["discount_mode"])
		self.assertEqual("175", usage["content"]["threshold_parameter"])
		self.assertEqual("168", usage["content"]["limited_hours"])
		self.assertIn("优惠券: 满减抵价券 | 抵扣 50 点券", item["display_text"])
		self.assertIn("价格条件参数: 175", item["display_text"])

	def test_item_module_resolves_preselection_options_to_final_entities(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9016",
				{"ID": "9016", "类型": "预选礼包"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("preselection_gift", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("2", usage["content"]["selection_mode_code"])
		self.assertEqual(3, usage["content"]["option_count"])
		self.assertEqual(
			["克里希·樱吹雪", "都市传说币", "莉莉安的舞蹈"],
			[option["entity_name"] for option in usage["content"]["options"]],
		)
		self.assertEqual(["预选择", "预选择物品"], [reference["sheet"] for reference in usage["references"]])
		self.assertIn("预选礼包: 配置 893 | 3 个候选 | 选择模式代码=2", item["display_text"])
		self.assertIn("英雄皮肤 10618 克里希·樱吹雪 ×1", item["display_text"])
		self.assertIn("道具 9010 都市传说币 ×300", item["display_text"])
		self.assertIn("局内动作 5100001 莉莉安的舞蹈 ×1", item["display_text"])

	def test_item_module_resolves_hour_trial_card_and_compensation(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9017",
				{"ID": "9017", "类型": "体验卡"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("trial_card", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("皮肤", usage["content"]["target_type"])
		self.assertEqual("克里希·樱吹雪", usage["content"]["target_name"])
		self.assertEqual("hour", usage["content"]["duration_unit"])
		self.assertEqual("12小时", usage["content"]["duration_label"])
		self.assertEqual("5", usage["content"]["owned_compensation_diamonds"])
		self.assertEqual("都市传说币", usage["content"]["auto_conversion"]["item_name"])
		self.assertEqual(
			["trial_card_target", "trial_card_conversion"],
			[reference["role"] for reference in usage["references"]],
		)
		self.assertIn("体验卡: 皮肤 10618 克里希·樱吹雪 | 12小时", item["display_text"])
		self.assertIn("已拥有补偿: 5 钻石", item["display_text"])
		self.assertIn("自动转换: 道具 9010 都市传说币 ×12", item["display_text"])

	def test_item_module_resolves_treasure_ticket_draws_and_latest_pool(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9018",
				{"ID": "9018", "类型": "夺宝抽奖券"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("treasure_draw_ticket", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("multi_system", usage["content"]["business_mode"])
		draw = usage["content"]["standard_draws"][0]
		self.assertEqual("1087", draw["draw_id"])
		self.assertEqual(["1", "5"], [option["cost_quantity"] for option in draw["draw_options"]])
		self.assertEqual("286", draw["latest_pool"]["pool_id"])
		self.assertEqual(10000, draw["latest_pool"]["total_probability_per_10000"])
		self.assertEqual("克里希·樱吹雪", draw["latest_pool"]["rewards"][0]["entity_name"])
		self.assertEqual("10001", usage["content"]["activity_draws"][0]["draw_id"])
		self.assertIn("业务模式: 常驻夺宝 + 活动抽奖", item["display_text"])
		self.assertIn("常驻夺宝: 普通（配置 1087） | 单抽×1券, 五连抽×5券 | 稀有保底 1-200 抽", item["display_text"])
		self.assertIn("最新奖池: 286 | 2 项 | 概率合计 10000/10000", item["display_text"])
		self.assertIn("活动抽奖: 10001 测试活动抽奖 | 奖池 292 | 单次消耗 1 券", item["display_text"])

	def test_item_module_resolves_loudspeaker_display_configuration(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9019",
				{"ID": "9019", "类型": "喇叭道具"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("loudspeaker", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("小喇叭", usage["content"]["loudspeaker_type"])
		self.assertEqual("全服聊天频道", usage["content"]["display_scope"])
		self.assertEqual("30", usage["content"]["character_limit"])
		self.assertEqual("3", usage["content"]["minimum_display_seconds"])
		self.assertEqual("10", usage["content"]["maximum_display_seconds"])
		self.assertEqual("1", usage["content"]["effect_parameter_2_code"])
		self.assertEqual("喇叭信息", usage["reference"]["sheet"])
		self.assertIn("喇叭道具: 小喇叭（配置 10041）", item["display_text"])
		self.assertIn("展示范围: 全服聊天频道 | 最多 30 字", item["display_text"])
		self.assertIn("显示时长: 3-10 秒", item["display_text"])

	def test_item_module_resolves_rank_protection_card_effect_and_window(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9020",
				{"ID": "9020", "类型": "排位守护卡"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("rank_protection_card", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("失败加星", usage["content"]["effect_type"])
		self.assertEqual("27", usage["content"]["effect_parameter_2_code"])
		self.assertEqual("168", usage["content"]["validity_hours"])
		self.assertEqual("7", usage["content"]["validity_days"])
		self.assertEqual("2026-08-01 00:00:00", usage["content"]["available_start_time"])
		self.assertEqual("2026-08-31 23:59:59", usage["content"]["available_end_time"])
		self.assertIn("排位守护卡: 失败加星", item["display_text"])
		self.assertIn("效果参数2: 27（原始代码，含义待确认）", item["display_text"])
		self.assertIn("道具有效期: 168 小时（7 天）", item["display_text"])

	def test_item_module_resolves_system_voice_with_server_priority(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9021",
				{"ID": "9021", "类型": "系统语音"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item = next(module for module in result["modules"] if module["module"] == "item")["items"][0]
		usage = item["category_usage"]
		self.assertEqual("system_voice", usage["kind"])
		self.assertTrue(usage["resolved"])
		self.assertEqual("超香的林襄语音", usage["content"]["title"])
		self.assertEqual("CV:林襄", usage["content"]["cv"])
		self.assertEqual("server", usage["content"]["source_kind"])
		self.assertEqual(["client", "server"], usage["content"]["available_sources"])
		self.assertEqual("2026-08-31 23:59:59", usage["content"]["end_time"])
		self.assertEqual("Play_5V5_sys_1_01", usage["content"]["previews"][0]["event"])
		self.assertEqual("svr系统语音配置", usage["reference"]["sheet"])
		self.assertIn("系统语音: 8 超香的林襄语音", item["display_text"])
		self.assertIn("配音: CV:林襄", item["display_text"])
		self.assertIn("生效配置: server / svr系统语音配置", item["display_text"])

	def test_item_module_highlights_hidden_item_in_detail_and_overview(self) -> None:
		with tempfile.TemporaryDirectory() as temporary_directory:
			write_item_source_priority_fixture(Path(temporary_directory))
			changeset = {"changes": [change(
				"【运营配置】41.道具信息表_Syndra.dtxml",
				"道具信息增量",
				"ID=9022",
				{"ID": "9022", "类型": "普通道具", "是否是隐藏道具": "1"},
			)]}
			result = ModuleRegistry().analyze(
				changeset,
				ModuleContext(tdr_root=temporary_directory, region_code="TW"),
			)

		item_module = next(module for module in result["modules"] if module["module"] == "item")
		item = item_module["items"][0]
		self.assertEqual({
			"field": "是否是隐藏道具",
			"raw_value": "1",
			"status": "hidden",
			"is_hidden": True,
			"needs_attention": True,
		}, item["hidden_item"])
		self.assertEqual(1, item_module["hidden_item_count"])
		self.assertIn("隐藏道具: 是（原始值=1）", item["display_text"])
		self.assertEqual(1, result["overview"]["hidden_item_count"])
		self.assertEqual("9022", result["overview"]["hidden_items"][0]["item_id"])
		self.assertIn("隐藏道具: 1个（9022 测试隐藏活动Token）", result["overview"]["display_text"])

	def test_item_hidden_flag_normalizes_explicit_visible_and_unknown_values(self) -> None:
		self.assertEqual("visible", ItemModule._hidden_item_state({"是否是隐藏道具": "否"})["status"])
		self.assertEqual("default_visible", ItemModule._hidden_item_state({})["status"])
		unknown = ItemModule._hidden_item_state({"是否是隐藏道具": "unexpected"})
		self.assertEqual("unknown", unknown["status"])
		self.assertTrue(unknown["needs_attention"])

	def test_item_unknown_and_deferred_changes_are_separated(self) -> None:
		changeset = {"changes": [
			change(
				"41.svr下发道具信息表_Syndra.dtxml",
				"道具信息",
				"ID=1",
				{"ID": "1", "名称": "测试道具", "图标地址": "item.png"},
			),
			change("未知表.dtxml", "Sheet1", "ID=2", {"ID": "2"}),
			change(
				"活动抽奖表.dtxml",
				"svr下发奖励池",
				"奖励池ID=3",
				{"奖励池ID": "3"},
				semantic_status="deferred",
			),
		]}
		result = ModuleRegistry().analyze(changeset, ModuleContext())
		self.assertEqual("partial", result["status"])
		self.assertEqual(1, result["summary"]["interpreted_change_count"])
		self.assertEqual(1, result["summary"]["module_not_found_count"])
		self.assertEqual(1, result["summary"]["deferred_change_count"])
		self.assertEqual("item", result["modules"][0]["module"])
		self.assertIn("道具: 1 测试道具", result["modules"][0]["items"][0]["display_text"])


if __name__ == "__main__":
	unittest.main()
