import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/price_history_entry.dart';
import 'product_search.dart';

final priceHistoryProvider =
    FutureProvider.autoDispose.family<List<PriceHistoryEntry>, String>((ref, id) async {
  final api = ref.watch(apiServiceProvider);
  return api.getPriceHistory(id);
});
