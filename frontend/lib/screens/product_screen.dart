import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/price_history.dart';
import '../providers/product_detail.dart';
import '../widgets/price_table.dart';

class ProductScreen extends ConsumerWidget {
  final String productId;
  const ProductScreen({super.key, required this.productId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final product = ref.watch(productDetailProvider(productId));
    final history = ref.watch(priceHistoryProvider(productId));

    return Scaffold(
      appBar: AppBar(title: const Text('Producto')),
      body: product.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Error: $e')),
        data: (p) => SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (p.offImageUrl != null)
                Center(
                  child: Image.network(
                    p.offImageUrl!,
                    height: 180,
                    errorBuilder: (_, __, ___) =>
                        const Icon(Icons.image_not_supported, size: 80),
                  ),
                )
              else
                const Center(
                  child: Icon(Icons.shopping_bag_outlined, size: 80),
                ),
              const SizedBox(height: 16),
              Text(p.name, style: Theme.of(context).textTheme.headlineSmall),
              if (p.brand != null) Text(p.brand!),
              if (p.offName != null && p.offName!.trim() != p.name.trim())
                Text(p.offName!, style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 24),
              Text('Histórico de precios',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              history.when(
                loading: () => const Padding(
                  padding: EdgeInsets.all(16),
                  child: Center(child: CircularProgressIndicator()),
                ),
                error: (e, _) => Text('Error: $e'),
                data: (entries) => PriceTable(entries: entries),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
