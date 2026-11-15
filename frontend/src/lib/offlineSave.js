import { apiPostOnce } from "./api";
import { enqueue, isNetworkError, newRef } from "./offlineQueue";

export const QUEUED_NOTE = "No internet — saved on this phone. It's sent by itself when the internet returns.";

/* Save now, or — with no internet — keep it on the phone and send it later.
   One ID for the record, so the first try and any retry are never recorded
   twice (offline_ref.py). Returns the server's answer, or { queued: true }. */
export async function saveOrQueue(path, body, label) {
  const ref = newRef();
  try {
    return await apiPostOnce(path, body, ref);
  } catch (e) {
    if (isNetworkError(e)) {
      enqueue(path, body, label, ref);
      return { queued: true };
    }
    throw e;
  }
}
