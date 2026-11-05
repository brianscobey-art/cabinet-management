import { useEffect } from "react";

/** The old CabinetTron ordering board. All ordering moved to Optimus (11/5/26),
 *  so old #/ordering links land there. */
export default function MovedToOptimus() {
  useEffect(() => {
    window.location.replace("/optimus");
  }, []);
  return (
    <p className="muted">
      Ordering moved to <a href="/optimus">Optimus</a>.
    </p>
  );
}
