import { Modal } from "../components/Modal";
import type { SelectionMode } from "./automatic-workflow";

export function SelectionModeDialog({ choose, close }: { choose: (mode: SelectionMode) => void; close: () => void }) {
  return <Modal title="通知作成の方法を選択" onClose={close} footer={<>
    <button className="admin-button" type="button" onClick={() => choose("auto")}>自動選択</button>
    <button className="admin-button secondary" type="button" onClick={() => choose("manual")}>マニュアル選択</button>
  </>}><p>自動選択では、評価5・LINE連携済みの会員を会員番号の新しい順に最大100人選び、保存・検証します。送信は最終確認後に確定します。</p></Modal>;
}
