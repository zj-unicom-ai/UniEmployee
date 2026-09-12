/**
 * 生成客户解决方案 Word 文档
 *
 * 被 enterprise-sales skill 调用，通过 execute("node scripts/gen_solution.js <参数>") 执行。
 * 使用 docx npm 包生成标准化的解决方案 Word 文档。
 *
 * 用法：
 *   node scripts/gen_solution.js <输出路径> <客户姓名> <企业名称> <需求分析> <产品清单JSON> <总金额> <备注>
 */

const path = require("path");
const fs = require("fs");

// 解析 docx 依赖：优先项目根 node_modules，其次全局 node_modules（npm root -g），
// 最后 NODE_PATH 环境变量。三处都没有时给出可执行的安装提示。
let docx;
try {
  docx = require("docx");
} catch (e) {
  const { execSync } = require("child_process");
  const globalRoot = execSync("npm root -g").toString().trim();
  process.env.NODE_PATH = [
    path.join(__dirname, "..", "..", "..", "..", "node_modules"),
    globalRoot,
    process.env.NODE_PATH,
  ].filter(Boolean).join(path.delimiter);
  require("module").Module._initPaths();
  try {
    docx = require("docx");
  } catch (e2) {
    console.error("docx 模块未找到，请先执行：npm install -g docx");
    process.exit(1);
  }
}
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, PageNumber, PageBreak, LevelFormat,
} = docx;

// ---- 解析命令行参数 ----
const args = process.argv.slice(2);
if (args.length < 3) {
  console.error("用法: node gen_solution.js <输出路径> <客户姓名> <企业名称> [需求分析] [产品清单JSON] [总金额]");
  process.exit(1);
}

const outputPath = args[0];
const customerName = args[1];
const company = args[2];
const analysis = args[3] || "";
const productsJson = args[4] || "[]";
const totalAmount = args[5] || "";

let products = [];
try { products = JSON.parse(productsJson); } catch (e) { products = []; }

// ---- 日期格式化 ----
const now = new Date();
const dateStr = `${now.getFullYear()}年${String(now.getMonth() + 1).padStart(2, "0")}月${String(now.getDate()).padStart(2, "0")}日`;

// ---- 文档样式 ----
const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };

// ---- 构建文档 ----
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial", color: "1E4073" },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: "47689A" },
        paragraph: { spacing: { before: 240, after: 160 }, outlineLevel: 1 },
      },
    ],
  },
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          size: { width: 11906, height: 16838 }, // A4
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
        },
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            alignment: AlignmentType.RIGHT,
            children: [new TextRun({ text: "客户解决方案", font: "Arial", size: 18, color: "999999" })],
          })],
        }),
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [
              new TextRun({ text: "第 ", size: 18, color: "999999" }),
              new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "999999" }),
              new TextRun({ text: " 页", size: 18, color: "999999" }),
            ],
          })],
        }),
      },
      children: [
        // ---- 封面标题 ----
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 100 },
          children: [new TextRun({ text: "客户解决方案", bold: true, size: 44, color: "1E4073" })],
        }),
        // ---- 副标题 ----
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 60 },
          children: [new TextRun({ text: `${customerName}${company ? "（" + company + "）" : ""}`, size: 28, color: "47689A" })],
        }),
        // ---- 日期 ----
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 400 },
          children: [new TextRun({ text: `编制日期：${dateStr}`, size: 18, color: "999999" })],
        }),

        // ---- 一、客户信息 ----
        new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("一、客户信息")] }),
        new Paragraph({
          spacing: { after: 120 },
          children: [
            new TextRun({ text: "客户名称：", bold: true, size: 22 }),
            new TextRun({ text: customerName, size: 22 }),
          ],
        }),
        ...(company
          ? [new Paragraph({
              spacing: { after: 200 },
              children: [
                new TextRun({ text: "所属企业：", bold: true, size: 22 }),
                new TextRun({ text: company, size: 22 }),
              ],
            })]
          : []),

        // ---- 二、需求分析 ----
        ...(analysis
          ? [
              new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("二、需求分析")] }),
              new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: analysis, size: 22 })] }),
            ]
          : []),

        // ---- 三、推荐产品方案 ----
        new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("三、推荐产品方案")] }),
        ...(products.length > 0
          ? [
              new Table({
                width: { size: 9026, type: WidthType.DXA },
                columnWidths: [3600, 1400, 1800, 2226],
                rows: [
                  // 表头
                  new TableRow({
                    children: ["产品名称", "数量", "单价（元）", "小计（元）"].map((h, i) =>
                      new TableCell({
                        borders,
                        width: { size: [3600, 1400, 1800, 2226][i], type: WidthType.DXA },
                        shading: { fill: "D5E8F0", type: ShadingType.CLEAR },
                        margins: { top: 60, bottom: 60, left: 100, right: 100 },
                        children: [new Paragraph({
                          children: [new TextRun({ text: h, bold: true, size: 20 })],
                        })],
                      })
                    ),
                  }),
                  // 数据行
                  ...products.map((p) =>
                    new TableRow({
                      children: [p.name, p.qty, p.price, p.subtotal].map((val, i) =>
                        new TableCell({
                          borders,
                          width: { size: [3600, 1400, 1800, 2226][i], type: WidthType.DXA },
                          margins: { top: 60, bottom: 60, left: 100, right: 100 },
                          children: [new Paragraph({
                            children: [new TextRun({ text: String(val), size: 20 })],
                          })],
                        })
                      ),
                    })
                  ),
                ],
              }),
            ]
          : []),
        // ---- 总金额 ----
        ...(totalAmount
          ? [
              new Paragraph({
                spacing: { before: 200 },
                children: [
                  new TextRun({ text: "方案总金额：", bold: true, size: 24 }),
                  new TextRun({ text: `¥${totalAmount}`, size: 28, color: "C0392B", bold: true }),
                ],
              }),
            ]
          : []),

        // ---- 四、方案优势 ----
        new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("四、方案优势")] }),
        ...[
          "本地化服务团队，专属客户经理与技术保障团队双线对接",
          "SLA 服务等级协议承诺，网络可用率 ≥ 99.9%（可按需升级）",
          "7×24 小时网络监控告警，P1 级故障 15 分钟响应",
          "云网一体的端到端交付，开通、组网、迁移统一负责",
          "支持按需扩容与多期演进规划，保护既有投资",
        ].map((a) =>
          new Paragraph({
            numbering: { reference: "bullets", level: 0 },
            children: [new TextRun({ text: a, size: 22 })],
          })
        ),

        // ---- 五、售后服务 ----
        new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("五、售后服务承诺")] }),
        new Paragraph({
          spacing: { after: 100 },
          children: [new TextRun({ text: "本方案所含服务均按以下标准提供保障：", size: 22 })],
        }),
        ...[
          "7×24 小时客服与故障受理热线，重大故障本地网范围内 30 分钟内到场",
          "专属客户经理月度回访，季度提供网络运行质量报告",
          "SLA 未达标按服务等级协议约定补偿",
          "重大保障期（产线检修、业务大促等）提供现场驻场支持",
        ].map((s) =>
          new Paragraph({
            numbering: { reference: "bullets", level: 0 },
            children: [new TextRun({ text: s, size: 22 })],
          })
        ),

        // ---- 页脚声明 ----
        new Paragraph({ spacing: { before: 400 } }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "— 本方案由数字员工自动生成，仅供参考 —", size: 18, color: "AAAAAA", italics: true })],
        }),
      ],
    },
  ],
});

// ---- 输出 ----
const outputDir = path.dirname(outputPath);
fs.mkdirSync(outputDir, { recursive: true });

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(outputPath, buffer);
  console.log(`文档已生成：${outputPath}`);
}).catch((err) => {
  console.error("生成文档失败:", err);
  process.exit(1);
});