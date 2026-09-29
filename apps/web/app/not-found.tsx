import Link from "next/link";

export default function NotFound() {
  return (
    <div className="max-w-lg space-y-3">
      <h1 className="text-xl font-semibold">Not found</h1>
      <p className="text-sm text-slate-600">This page or document does not exist.</p>
      <Link href="/" className="text-sm underline">
        Back to documents
      </Link>
    </div>
  );
}
