import type { MutationFunction, QueryClient, QueryKey, UseMutationOptions } from "@tanstack/react-query";

export type OptimisticMutationSnapshot<TCacheData> = [QueryKey, TCacheData | undefined];

export type OptimisticMutationContext<TCacheData> = {
  snapshots: OptimisticMutationSnapshot<TCacheData>[];
};

type CreateOptimisticMutationOptions<TData, TVariables, TCacheData> = {
  mutationFn: MutationFunction<TData, TVariables>;
  optimisticUpdate: (
    current: TCacheData | undefined,
    variables: TVariables,
    snapshots: OptimisticMutationSnapshot<TCacheData>[],
  ) => TCacheData | undefined;
  queryClient: QueryClient;
  queryKey: QueryKey;
  revertOnError?: boolean;
};

export function createOptimisticMutation<TData, TError = Error, TVariables = void, TCacheData = unknown>({
  mutationFn,
  optimisticUpdate,
  queryClient,
  queryKey,
  revertOnError = true,
}: CreateOptimisticMutationOptions<TData, TVariables, TCacheData>): UseMutationOptions<
  TData,
  TError,
  TVariables,
  OptimisticMutationContext<TCacheData>
> {
  return {
    mutationFn,
    onError: (_error, _variables, context) => {
      if (!revertOnError) {
        return;
      }

      context?.snapshots.forEach(([snapshotQueryKey, data]) => {
        queryClient.setQueryData(snapshotQueryKey, data);
      });
    },
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey });

      const snapshots = queryClient.getQueriesData<TCacheData>({ queryKey });
      queryClient.setQueriesData<TCacheData>({ queryKey }, (current) =>
        optimisticUpdate(current, variables, snapshots),
      );

      return { snapshots };
    },
  };
}
