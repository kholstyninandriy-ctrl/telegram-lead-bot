import listingsData from "@/data/listings.json";

export interface Listing {
  id: string;
  address: string;
  neighborhood: string;
  propertyType: string;
  status: string;
  price: number;
  beds: number;
  baths: number;
  sqft: number;
  yearBuilt: number;
  highlights: string[];
  image: string;
  /** Shown in the website's own grid; the rest surface through the assistant. */
  featured: boolean;
}

export const listings = listingsData as Listing[];

export interface ListingFilters {
  minPrice?: number;
  maxPrice?: number;
  minBeds?: number;
  neighborhood?: string;
  propertyType?: string;
}

export function searchListings(filters: ListingFilters, limit = 4): Listing[] {
  const neighborhood = filters.neighborhood?.trim().toLowerCase();
  const propertyType = filters.propertyType?.trim().toLowerCase();

  const matches = listings.filter((listing) => {
    if (filters.minPrice !== undefined && listing.price < filters.minPrice) return false;
    if (filters.maxPrice !== undefined && listing.price > filters.maxPrice) return false;
    if (filters.minBeds !== undefined && listing.beds < filters.minBeds) return false;
    if (neighborhood && !listing.neighborhood.toLowerCase().includes(neighborhood)) return false;
    if (propertyType && listing.propertyType.toLowerCase() !== propertyType) return false;
    return true;
  });

  // Cheapest first: a buyer who names a budget is usually anchored to its low end.
  return matches.sort((a, b) => a.price - b.price).slice(0, limit);
}

export function findListing(id: string): Listing | undefined {
  return listings.find((listing) => listing.id.toLowerCase() === id.trim().toLowerCase());
}

export const formatPrice = (price: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(price);
