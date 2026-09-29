import { redirect } from "next/navigation";

// Documents live on the home page; old links and bookmarks still land there.
export default function DocumentsPage() {
  redirect("/");
}
