import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/product.dart';
import 'product_search.dart';

final productDetailProvider =
    FutureProvider.autoDispose.family<Product, String>((ref, id) async {
  final api = ref.watch(apiServiceProvider);
  return api.getProduct(id);
});
