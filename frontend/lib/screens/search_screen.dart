import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../providers/product_search.dart';
import '../widgets/debounced_search_field.dart';
import '../widgets/product_tile.dart';

class SearchScreen extends ConsumerWidget {
  const SearchScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final results = ref.watch(productSearchProvider);
    final hasQuery = ref.watch(searchQueryProvider).isNotEmpty;

    return Scaffold(
      appBar: AppBar(title: const Text('Grocery Receipt')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            DebouncedSearchField(
              onChanged: (v) =>
                  ref.read(searchQueryProvider.notifier).state = v.trim(),
            ),
            const SizedBox(height: 16),
            Expanded(
              child: results.when(
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (e, _) => Center(child: Text('Error: $e')),
                data: (products) {
                  if (!hasQuery) {
                    return const Center(child: Text('Escribe para buscar productos.'));
                  }
                  if (products.isEmpty) {
                    return const Center(child: Text('Sin resultados.'));
                  }
                  return ListView.separated(
                    itemCount: products.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (ctx, i) => ProductTile(
                      product: products[i],
                      onTap: () => context.go('/product/${products[i].id}'),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}
