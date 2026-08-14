import { LoadingRegion, SkeletonCard, SkeletonPageHeading } from '@/components/ui';

// Shown the instant this route is requested. Without it Next keeps the previous
// page on screen for the whole server round trip and the click looks ignored.
export default function Loading() {
  return (
    <LoadingRegion label="Loading settings">
      <SkeletonPageHeading />
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <SkeletonCard rows={4} />
        <SkeletonCard rows={4} />
      </div>
    </LoadingRegion>
  );
}
