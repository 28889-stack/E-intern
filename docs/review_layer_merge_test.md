# Review Layer Merge Test

Test date: 2026-06-20

## End-to-end regression

- Test case_id: `case_022`
- Material type: account transaction material, Guangfa PDF statement
- Upload route: `POST /api/cases/case_022/account-info/files`
- Route type: `direct_pdf`
- Content type: `guangfa`
- Process status: `parsed`
- Extract status: `success`
- Finalize: success, `POST /api/cases/case_022/finalize` returned 200
- Export before saving review: returned 409 with `请先保存人工复核结果，再导出 Excel`
- Review load: `GET /api/cases/case_022/review` returned 200
- Review save: `POST /api/cases/case_022/review` returned 200
- Review status after save: `review_saved = true`, `excel_export_allowed = true`
- Export after saving review: `GET /api/cases/case_022/export/excel` returned 200
- Modified value checked in Excel: `合并验收修改证券`
- Excel reflected modified value: yes

## Notes

- The generated runtime case data lives under `data/cases/case_022/` and is ignored by git.
- The exported Excel path was `data/cases/case_022/final/case_022_final.xlsx` and is ignored by git.
