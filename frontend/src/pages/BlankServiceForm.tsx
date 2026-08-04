import { ServiceRequestDetail } from "../api";
import { ServiceReportPrint } from "./ServiceRequestPage";

const EMPTY: ServiceRequestDetail = {
  id: 0,
  job_id: 0,
  job_code: null,
  address: "",
  account_name: null,
  community_name: null,
  lot_number: null,
  title: null,
  status: "",
  created_by: null,
  created_at: new Date().toISOString(),
  parts: [],
  lines: [],
  rooms: [],
  hardware: [],
};

export default function BlankServiceForm() {
  return (
    <div className="service-page">
      <p className="back-row no-print">
        <a href="#/forms/service">← Service forms</a>
      </p>
      <div className="page-head no-print">
        <h2>Blank Service Request</h2>
        <button onClick={() => window.print()}>🖨 Print</button>
      </div>
      <p className="muted no-print">A blank form to print and fill in by hand.</p>
      <div className="blank-preview">
        <ServiceReportPrint sr={EMPTY} partNumber={() => null} partById={() => null} blank screen />
      </div>
    </div>
  );
}
