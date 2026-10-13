import { registrationLowerBound } from "./job-registration";

export function JobDateFilter({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const invalid = Boolean(value) && registrationLowerBound(value) === null;
  return <div className="admin-actions job-date-filter">
    <label>登録日（日本時間・この日以降）<input type="date" value={value} max="9999-12-31" aria-invalid={invalid} onChange={(event) => onChange(event.target.value)} /></label>
    <button className="admin-button secondary compact" type="button" disabled={!value} onClick={() => onChange("")}>解除</button>
    {invalid && <span role="alert">有効な日付を入力してください。</span>}
    <small>登録日が未取得の求人は、日付指定時には表示されません。</small>
  </div>;
}
