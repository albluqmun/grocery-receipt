import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/product.dart';
import 'api.dart';

final searchQueryProvider = StateProvider<String>((ref) => '');

final productSearchProvider = FutureProvider.autoDispose<List<Product>>((ref) async {
  final q = ref.watch(searchQueryProvider);
  if (q.isEmpty) return const <Product>[];
  final api = ref.watch(apiServiceProvider);
  return api.searchProducts(q);
});
